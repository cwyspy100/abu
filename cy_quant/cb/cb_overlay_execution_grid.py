"""固定 Overlay + 基础参数网格（OOS）研究。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode
from cy_quant.cb.cb_drawdown_overlay_research import apply_overlay, summarize_overlay
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


FIXED_OVERLAY = {
    "dd_mild": -0.10,
    "dd_deep": -0.14,
    "exp_mild": 0.75,
    "exp_deep": 0.65,
    "loss_th": -0.04,
    "cooldown_periods": 1,
    "cooldown_exp": 0.50,
    "vol_lookback": 6,
    "vol_target": 0.020,
    "vol_floor": 0.50,
}


def _oos_split(base_rets: pd.Series, train_periods: int, test_periods: int, step: int) -> tuple[pd.Series, pd.Series]:
    n = len(base_rets)
    start = train_periods
    base_oos: List[float] = []
    overlay_oos: List[float] = []
    while start + test_periods <= n:
        te = base_rets.iloc[start : start + test_periods].reset_index(drop=True)
        ov = apply_overlay(te, **FIXED_OVERLAY)
        base_oos.extend([float(x) for x in te.tolist()])
        overlay_oos.extend([float(x) for x in ov["ret"].tolist()])
        start += step
    return pd.Series(base_oos), pd.Series(overlay_oos)


def _metrics_delta(base_ret: pd.Series, overlay_ret: pd.Series) -> Dict[str, float]:
    b = summarize_overlay(pd.DataFrame({"ret": base_ret, "exposure": 1.0}))
    o = summarize_overlay(pd.DataFrame({"ret": overlay_ret, "exposure": 1.0}))
    return {
        "base_ann_return": b["ann_return"],
        "base_total_return": b["total_return"],
        "base_max_drawdown": b["max_drawdown"],
        "base_win_rate": b["win_rate"],
        "overlay_ann_return": o["ann_return"],
        "overlay_total_return": o["total_return"],
        "overlay_max_drawdown": o["max_drawdown"],
        "overlay_win_rate": o["win_rate"],
        "delta_ann": o["ann_return"] - b["ann_return"],
        "delta_total": o["total_return"] - b["total_return"],
        "delta_mdd_improve": abs(b["max_drawdown"]) - abs(o["max_drawdown"]),
        "delta_win_rate": o["win_rate"] - b["win_rate"],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="固定 Overlay + 基础参数网格 OOS 研究")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--train-periods", type=int, default=12)
    p.add_argument("--test-periods", type=int, default=3)
    p.add_argument("--step", type=int, default=3)
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    rows: List[Dict[str, float]] = []
    for top_n in [10, 15, 20, 25, 30]:
        for min_amount in [1500, 2000, 3000]:
            for cost_bps in [20, 40, 60]:
                base_df = run_mode(
                    panel=panel,
                    mode="balanced_premium",
                    top_n=top_n,
                    min_amount_wan=float(min_amount),
                    cost_bps=float(cost_bps),
                ).reset_index(drop=True)
                if base_df.empty:
                    continue

                base_ret = base_df["ret"].astype(float)
                full_base = summarize_overlay(pd.DataFrame({"ret": base_ret, "exposure": 1.0}))
                full_ov = summarize_overlay(
                    apply_overlay(base_ret.reset_index(drop=True), **FIXED_OVERLAY)
                )

                oos_base, oos_overlay = _oos_split(
                    base_rets=base_ret,
                    train_periods=args.train_periods,
                    test_periods=args.test_periods,
                    step=args.step,
                )
                if oos_base.empty or oos_overlay.empty:
                    continue

                oos = _metrics_delta(oos_base, oos_overlay)

                rows.append(
                    {
                        "top_n": top_n,
                        "min_amount_wan": min_amount,
                        "cost_bps": cost_bps,
                        "full_base_ann": full_base["ann_return"],
                        "full_base_mdd": full_base["max_drawdown"],
                        "full_overlay_ann": full_ov["ann_return"],
                        "full_overlay_mdd": full_ov["max_drawdown"],
                        "oos_periods": int(len(oos_base)),
                        **oos,
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("无可用结果，请检查输入数据或参数。")

    # OOS 主排序：优先回撤改善，其次年化不降
    out["oos_score"] = out["delta_mdd_improve"] * 100.0 + out["overlay_ann_return"] * 30.0
    out = out.sort_values(["oos_score", "delta_ann"], ascending=[False, False]).reset_index(drop=True)
    winners = out[(out["delta_mdd_improve"] > 0) & (out["delta_ann"] >= 0)].copy()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_overlay_exec_grid_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.to_csv(os.path.join(out_dir, "overlay_exec_grid.csv"), index=False, encoding="utf-8-sig")
    winners.to_csv(os.path.join(out_dir, "overlay_exec_winners.csv"), index=False, encoding="utf-8-sig")

    print(f"执行网格研究完成 -> {out_dir}")
    print("Top 10 by oos_score:")
    print(
        out[
            [
                "top_n",
                "min_amount_wan",
                "cost_bps",
                "overlay_ann_return",
                "overlay_max_drawdown",
                "delta_ann",
                "delta_mdd_improve",
                "oos_score",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )
    print(f"winners (delta_ann>=0 & delta_mdd_improve>0): {len(winners)}")


if __name__ == "__main__":
    main()

