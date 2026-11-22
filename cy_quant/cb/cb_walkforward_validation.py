"""可转债策略 Walk-Forward 验证（真实强赎过滤）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_combo_monthly_backtest import run_backtest
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def eval_subset(perf: pd.DataFrame) -> Dict[str, float]:
    if perf.empty:
        return {"periods": 0, "ann_return": np.nan, "total_return": np.nan, "max_drawdown": np.nan, "win_rate": np.nan}
    equity = (1.0 + perf["period_ret_20d"]).cumprod()
    total = float(equity.iloc[-1] - 1.0)
    periods = len(perf)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / periods) - 1.0) if periods > 0 else np.nan
    roll_max = equity.cummax()
    mdd = float((equity / roll_max - 1.0).min())
    wr = float((perf["period_ret_20d"] > 0).mean())
    return {"periods": periods, "ann_return": ann, "total_return": total, "max_drawdown": mdd, "win_rate": wr}


def train_score(perf: pd.DataFrame) -> float:
    s = eval_subset(perf)
    if s["periods"] == 0 or pd.isna(s["ann_return"]) or pd.isna(s["max_drawdown"]):
        return -1e9
    # 收益优先，回撤与胜率约束
    return s["ann_return"] * 100 - abs(s["max_drawdown"]) * 80 + s["win_rate"] * 10


def main() -> None:
    p = argparse.ArgumentParser(description="可转债 walk-forward 验证")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--train-periods", type=int, default=12)
    p.add_argument("--test-periods", type=int, default=3)
    p.add_argument("--step", type=int, default=3)
    p.add_argument("--cost-bps", type=float, default=40.0)
    p.add_argument("--top-k", type=int, default=1, help="每个fold训练后选取前K个参数做等权集成，1=单参数")
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_walkforward_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    intervals = build_real_call_intervals(args.cb_call)
    panel = apply_real_call_filter(panel, intervals)

    # 候选参数集：沿用前轮搜索高频可行区间
    candidates: List[Dict[str, object]] = []
    for st in ["combo_dl_trend", "combo_dl_trend_call", "combo_lp_trend"]:
        for top_n in [15, 20, 25, 30]:
            for min_amt in [2000, 3000]:
                candidates.append({
                    "strategy": st,
                    "top_n": top_n,
                    "min_amount_wan": min_amt,
                    "cost_bps": args.cost_bps,
                })

    # 预计算每个候选的全期 perf，后续按窗口切片
    perf_map: Dict[str, pd.DataFrame] = {}
    for c in candidates:
        key = f"{c['strategy']}|{c['top_n']}|{c['min_amount_wan']}|{c['cost_bps']}"
        perf, _ = run_backtest(
            panel,
            c["strategy"],
            top_n=int(c["top_n"]),
            min_amount_wan=float(c["min_amount_wan"]),
            max_price_for_call_risk=9999.0,
            roundtrip_cost_bps=float(c["cost_bps"]),
        )
        perf = perf.sort_values("rebalance_date").reset_index(drop=True)
        perf_map[key] = perf

    # 以第一个候选的时序作为基准（应一致）
    sample_key = next(iter(perf_map.keys()))
    base_perf = perf_map[sample_key]
    n = len(base_perf)

    wf_rows = []
    oos_returns = []

    start = args.train_periods
    while start + args.test_periods <= n:
        train_idx = list(range(start - args.train_periods, start))
        test_idx = list(range(start, start + args.test_periods))

        # 训练集选参
        scored = []
        for key, perf in perf_map.items():
            if perf.empty or len(perf) < max(test_idx) + 1:
                continue
            train_perf = perf.iloc[train_idx].copy()
            sc = train_score(train_perf)
            scored.append((key, sc))

        if not scored:
            break

        scored.sort(key=lambda x: x[1], reverse=True)
        sel = scored[: max(1, int(args.top_k))]
        sel_keys = [k for k, _ in sel]

        # 测试集评估：top-k 等权集成
        test_mat = []
        for key in sel_keys:
            ptest = perf_map[key].iloc[test_idx].copy()
            test_mat.append(ptest["period_ret_20d"].values)
        test_arr = np.array(test_mat)
        test_ens = test_arr.mean(axis=0)
        test_perf = pd.DataFrame({"period_ret_20d": test_ens})
        test_stat = eval_subset(test_perf)
        oos_returns.extend([float(x) for x in test_ens.tolist()])

        # 训练统计也用 top-k 集成口径
        train_mat = []
        for key in sel_keys:
            ptrain = perf_map[key].iloc[train_idx].copy()
            train_mat.append(ptrain["period_ret_20d"].values)
        train_arr = np.array(train_mat)
        train_ens = train_arr.mean(axis=0)
        train_perf = pd.DataFrame({"period_ret_20d": train_ens})
        train_stat = eval_subset(train_perf)

        t0 = str(base_perf.iloc[test_idx[0]]["rebalance_date"])[:10]
        t1 = str(base_perf.iloc[test_idx[-1]]["rebalance_date"])[:10]

        wf_rows.append(
            {
                "test_start": t0,
                "test_end": t1,
                "best_key": " ; ".join(sel_keys),
                "train_ann": train_stat["ann_return"],
                "train_mdd": train_stat["max_drawdown"],
                "test_ann": test_stat["ann_return"],
                "test_total_return": test_stat["total_return"],
                "test_mdd": test_stat["max_drawdown"],
                "test_win_rate": test_stat["win_rate"],
                "test_periods": test_stat["periods"],
            }
        )

        start += args.step

    wf_df = pd.DataFrame(wf_rows)
    wf_path = os.path.join(out_dir, "walkforward_folds.csv")
    wf_df.to_csv(wf_path, index=False, encoding="utf-8-sig")

    # 汇总 OOS
    if oos_returns:
        oos = pd.DataFrame({"ret": oos_returns})
        equity = (1.0 + oos["ret"]).cumprod()
        total = float(equity.iloc[-1] - 1.0)
        periods = len(oos)
        ann = float((1.0 + total) ** ((252.0 / 20.0) / periods) - 1.0)
        mdd = float((equity / equity.cummax() - 1.0).min())
        wr = float((oos["ret"] > 0).mean())
    else:
        total = np.nan
        periods = 0
        ann = np.nan
        mdd = np.nan
        wr = np.nan

    summary = pd.DataFrame(
        [
            {
                "folds": len(wf_df),
                "oos_periods": periods,
                "oos_total_return": total,
                "oos_ann_return": ann,
                "oos_max_drawdown": mdd,
                "oos_win_rate": wr,
            }
        ]
    )
    sum_path = os.path.join(out_dir, "walkforward_summary.csv")
    summary.to_csv(sum_path, index=False, encoding="utf-8-sig")

    print(f"walk-forward 完成 -> {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
