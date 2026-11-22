"""balanced_premium 稳健性与统计显著性研究。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter
from cy_quant.cb.cb_diversification_research import (
    pick_top,
    pick_balanced_premium,
    summarize_returns,
)


def run_rets(panel: pd.DataFrame, mode: str, top_n: int, min_amount_wan: float, cost_bps: float) -> pd.DataFrame:
    d = panel.dropna(subset=["score", "fwd_ret_20d", "trade_date"]).copy()
    d = d[d["amount"] >= min_amount_wan].copy()
    d["month"] = d["trade_date"].dt.to_period("M")
    rebal_dates = d.groupby("month")["trade_date"].max().sort_values().tolist()

    prev = set()
    rows = []
    for dt in rebal_dates:
        cross = d[d["trade_date"] == dt].copy().sort_values("score", ascending=False)
        if len(cross) < top_n:
            continue

        if mode == "baseline":
            picks = pick_top(cross, top_n)
        elif mode == "balanced_premium":
            picks = pick_balanced_premium(cross, top_n)
        else:
            raise ValueError(mode)

        if len(picks) < top_n:
            miss = top_n - len(picks)
            rest = cross[~cross["ts_code"].isin(set(picks["ts_code"]))].head(miss)
            picks = pd.concat([picks, rest], ignore_index=True)

        gross = float(picks["fwd_ret_20d"].mean())
        cur = set(picks["ts_code"].astype(str).tolist())
        turn = 1.0 if not prev else 1.0 - len(prev & cur) / float(top_n)
        cost = turn * (cost_bps / 10000.0)
        net = gross - cost
        rows.append({"rebalance_date": pd.to_datetime(dt), "ret": net, "turnover": turn})
        prev = cur

    return pd.DataFrame(rows)


def ann_from_total(total: float, periods: int) -> float:
    if periods <= 0:
        return np.nan
    return float((1.0 + total) ** ((252.0 / 20.0) / periods) - 1.0)


def block_bootstrap_diff(base_ret: np.ndarray, bp_ret: np.ndarray, n_boot: int = 5000, block: int = 3, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(base_ret)
    out = []
    for _ in range(n_boot):
        idx = []
        while len(idx) < n:
            s = int(rng.integers(0, max(1, n - block + 1)))
            idx.extend(list(range(s, min(n, s + block))))
        idx = idx[:n]
        b = base_ret[idx]
        p = bp_ret[idx]
        b_total = float(np.prod(1.0 + b) - 1.0)
        p_total = float(np.prod(1.0 + p) - 1.0)
        out.append(
            {
                "delta_total": p_total - b_total,
                "delta_ann": ann_from_total(p_total, n) - ann_from_total(b_total, n),
            }
        )
    return pd.DataFrame(out)


def main() -> None:
    p = argparse.ArgumentParser(description="balanced_premium 稳健性研究")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]

    basic = pd.read_csv(args.cb_basic, dtype={"ts_code": str, "stk_code": str})
    basic = basic[["ts_code", "stk_code"]].drop_duplicates(subset=["ts_code"], keep="first")
    panel = panel.merge(basic, on="ts_code", how="left")
    panel["stk_code"] = panel["stk_code"].fillna(panel["ts_code"])
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    rows = []
    series_map = {}
    for top_n in [20, 25, 30]:
        for min_amt in [1500, 2000, 2500, 3000]:
            for cost in [40, 60]:
                b = run_rets(panel, "baseline", top_n, min_amt, cost)
                p2 = run_rets(panel, "balanced_premium", top_n, min_amt, cost)
                n = min(len(b), len(p2))
                if n == 0:
                    continue
                b = b.tail(n).reset_index(drop=True)
                p2 = p2.tail(n).reset_index(drop=True)

                sb = summarize_returns(b["ret"].tolist())
                sp = summarize_returns(p2["ret"].tolist())

                rows.append(
                    {
                        "top_n": top_n,
                        "min_amount_wan": min_amt,
                        "cost_bps": cost,
                        "periods": n,
                        "base_ann": sb["ann_return"],
                        "bp_ann": sp["ann_return"],
                        "base_total": sb["total_return"],
                        "bp_total": sp["total_return"],
                        "base_mdd": sb["max_drawdown"],
                        "bp_mdd": sp["max_drawdown"],
                        "delta_ann": sp["ann_return"] - sb["ann_return"],
                        "delta_total": sp["total_return"] - sb["total_return"],
                        "delta_mdd": abs(sb["max_drawdown"]) - abs(sp["max_drawdown"]),
                    }
                )
                key = (top_n, min_amt, cost)
                series_map[key] = (b["ret"].values.astype(float), p2["ret"].values.astype(float))

    grid = pd.DataFrame(rows)
    grid["score"] = grid["delta_ann"] * 100 + grid["delta_mdd"] * 50
    grid = grid.sort_values("score", ascending=False).reset_index(drop=True)

    best = grid.iloc[0]
    key = (int(best["top_n"]), int(best["min_amount_wan"]), int(best["cost_bps"]))
    base_ret, bp_ret = series_map[key]
    boot = block_bootstrap_diff(base_ret, bp_ret, n_boot=5000, block=3, seed=7)

    prob_win = float((boot["delta_total"] > 0).mean())
    ci_low = float(boot["delta_total"].quantile(0.05))
    ci_high = float(boot["delta_total"].quantile(0.95))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_bp_robustness_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    grid.to_csv(os.path.join(out_dir, "bp_robust_grid.csv"), index=False, encoding="utf-8-sig")
    boot.to_csv(os.path.join(out_dir, "bp_bootstrap.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(
        [
            {
                "best_top_n": key[0],
                "best_min_amount_wan": key[1],
                "best_cost_bps": key[2],
                "base_total": float(np.prod(1.0 + base_ret) - 1.0),
                "bp_total": float(np.prod(1.0 + bp_ret) - 1.0),
                "prob_bp_better": prob_win,
                "delta_total_ci05": ci_low,
                "delta_total_ci95": ci_high,
            }
        ]
    )
    summary.to_csv(os.path.join(out_dir, "bp_robust_summary.csv"), index=False, encoding="utf-8-sig")

    print(f"稳健性研究完成 -> {out_dir}")
    print(grid.head(10).to_string(index=False))
    print("\nBootstrap summary:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
