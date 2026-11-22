"""可转债策略容量与冲击成本压力测试。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_research import pick_balanced_premium, summarize_returns
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def run_with_impact(
    panel: pd.DataFrame,
    top_n: int,
    min_amount_wan: float,
    base_cost_bps: float,
    capital_cny: float,
    impact_k_bps: float,
) -> dict:
    """
    impact模型（启发式）：
    participation = traded_notional_per_bond / ADV
    impact_bps = k * sqrt(participation)
    每期额外冲击成本 = mean(impact_bps_of_traded_bonds) / 10000
    """
    d = panel.dropna(subset=["score", "fwd_ret_20d", "trade_date", "amount"]).copy()
    d = d[d["amount"] >= min_amount_wan].copy()
    d["month"] = d["trade_date"].dt.to_period("M")
    rebal_dates = d.groupby("month")["trade_date"].max().sort_values().tolist()

    prev = set()
    rets = []
    turns = []
    impacts = []

    for dt in rebal_dates:
        cross = d[d["trade_date"] == dt].copy().sort_values("score", ascending=False)
        if len(cross) < top_n:
            continue

        picks = pick_balanced_premium(cross, top_n)
        if len(picks) < top_n:
            miss = top_n - len(picks)
            rest = cross[~cross["ts_code"].isin(set(picks["ts_code"]))].head(miss)
            picks = pd.concat([picks, rest], ignore_index=True)

        gross = float(picks["fwd_ret_20d"].mean())
        cur = set(picks["ts_code"].astype(str).tolist())
        turn = 1.0 if not prev else 1.0 - len(prev & cur) / float(top_n)

        # 基础换手成本
        base_cost = turn * (base_cost_bps / 10000.0)

        # 冲击成本（只对换手部分估算）
        if turn <= 0:
            impact_cost = 0.0
        else:
            traded_per_bond = capital_cny * turn / float(top_n)
            adv_cny = picks["amount"].astype(float).values * 10000.0
            participation = np.clip(traded_per_bond / np.maximum(adv_cny, 1.0), 0.0, None)
            impact_bps_each = impact_k_bps * np.sqrt(participation)
            impact_cost = float(np.mean(impact_bps_each) / 10000.0)

        net = gross - base_cost - impact_cost

        rets.append(net)
        turns.append(turn)
        impacts.append(impact_cost)
        prev = cur

    m = summarize_returns(rets)
    m["avg_turnover"] = float(np.mean(turns)) if turns else np.nan
    m["avg_impact_cost"] = float(np.mean(impacts)) if impacts else np.nan
    return m


def main() -> None:
    p = argparse.ArgumentParser(description="容量与冲击成本压力测试")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument("--min-amount-wan", type=float, default=2000)
    p.add_argument("--base-cost-bps", type=float, default=40)
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    capitals = [5_000_000, 20_000_000, 50_000_000, 100_000_000, 200_000_000]
    impact_ks = [10, 15, 20]

    rows: List[dict] = []
    for cap in capitals:
        for k in impact_ks:
            s = run_with_impact(
                panel,
                top_n=args.top_n,
                min_amount_wan=args.min_amount_wan,
                base_cost_bps=args.base_cost_bps,
                capital_cny=float(cap),
                impact_k_bps=float(k),
            )
            s.update(
                {
                    "capital_cny": int(cap),
                    "impact_k_bps": float(k),
                }
            )
            rows.append(s)

    out = pd.DataFrame(rows)
    out = out[
        [
            "capital_cny",
            "impact_k_bps",
            "periods",
            "ann_return",
            "total_return",
            "max_drawdown",
            "win_rate",
            "avg_turnover",
            "avg_impact_cost",
        ]
    ]
    out["score"] = out["ann_return"] * 100 - out["max_drawdown"].abs() * 80 + out["win_rate"] * 10

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_capacity_stress_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.to_csv(os.path.join(out_dir, "capacity_stress.csv"), index=False, encoding="utf-8-sig")

    print(f"容量压力测试完成 -> {out_dir}")
    print(out.sort_values(["capital_cny", "impact_k_bps"]).to_string(index=False))


if __name__ == "__main__":
    main()
