"""固定 Overlay 实盘执行配置脚本（可切换参数档位）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict

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


PROFILES: Dict[str, Dict[str, float]] = {
    # 收益与流动性平衡（当前默认推荐）
    "balanced": {"top_n": 25, "min_amount_wan": 2000, "cost_bps": 40},
    # 回撤优先（更防守）
    "defensive": {"top_n": 15, "min_amount_wan": 1500, "cost_bps": 40},
}


def run_profile(
    panel: pd.DataFrame,
    top_n: int,
    min_amount_wan: float,
    cost_bps: float,
) -> pd.DataFrame:
    base = run_mode(panel, "balanced_premium", top_n, min_amount_wan, cost_bps).reset_index(drop=True)
    if base.empty:
        return pd.DataFrame()
    ov = apply_overlay(base["ret"].astype(float).reset_index(drop=True), **FIXED_OVERLAY)
    out = base.copy()
    out["overlay_ret"] = ov["ret"].values
    out["overlay_exposure"] = ov["exposure"].values
    return out


def _summary(df: pd.DataFrame, col: str) -> Dict[str, float]:
    if df.empty:
        return {"periods": 0, "ann_return": float("nan"), "total_return": float("nan"), "max_drawdown": float("nan"), "win_rate": float("nan"), "avg_exposure": float("nan")}
    if col == "ret":
        return summarize_overlay(pd.DataFrame({"ret": df["ret"], "exposure": 1.0}))
    return summarize_overlay(pd.DataFrame({"ret": df[col], "exposure": df["overlay_exposure"]}))


def main() -> None:
    p = argparse.ArgumentParser(description="固定 Overlay 配置化执行脚本")
    p.add_argument("--profile", choices=sorted(PROFILES.keys()), default="balanced")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--recent-periods", type=int, default=12, help="最近N期观察窗口")
    args = p.parse_args()

    cfg = PROFILES[args.profile]
    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    perf = run_profile(
        panel=panel,
        top_n=int(cfg["top_n"]),
        min_amount_wan=float(cfg["min_amount_wan"]),
        cost_bps=float(cfg["cost_bps"]),
    )
    if perf.empty:
        raise RuntimeError("无可用收益序列，请检查数据与参数。")

    perf["base_equity"] = (1.0 + perf["ret"]).cumprod()
    perf["overlay_equity"] = (1.0 + perf["overlay_ret"]).cumprod()

    full_base = _summary(perf, "ret")
    full_overlay = _summary(perf, "overlay_ret")

    recent = perf.tail(int(args.recent_periods)).copy()
    rec_base = _summary(recent, "ret")
    rec_overlay = _summary(recent, "overlay_ret")

    summary = pd.DataFrame(
        [
            {"scope": "full", "mode": "base", **full_base},
            {"scope": "full", "mode": "overlay", **full_overlay},
            {"scope": "full", "mode": "delta_overlay_minus_base", "periods": full_overlay["periods"], "ann_return": full_overlay["ann_return"] - full_base["ann_return"], "total_return": full_overlay["total_return"] - full_base["total_return"], "max_drawdown": abs(full_base["max_drawdown"]) - abs(full_overlay["max_drawdown"]), "win_rate": full_overlay["win_rate"] - full_base["win_rate"], "avg_exposure": full_overlay["avg_exposure"] - 1.0},
            {"scope": f"recent_{args.recent_periods}", "mode": "base", **rec_base},
            {"scope": f"recent_{args.recent_periods}", "mode": "overlay", **rec_overlay},
            {"scope": f"recent_{args.recent_periods}", "mode": "delta_overlay_minus_base", "periods": rec_overlay["periods"], "ann_return": rec_overlay["ann_return"] - rec_base["ann_return"], "total_return": rec_overlay["total_return"] - rec_base["total_return"], "max_drawdown": abs(rec_base["max_drawdown"]) - abs(rec_overlay["max_drawdown"]), "win_rate": rec_overlay["win_rate"] - rec_base["win_rate"], "avg_exposure": rec_overlay["avg_exposure"] - 1.0},
        ]
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_overlay_profile_{args.profile}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    perf.to_csv(os.path.join(out_dir, "profile_period_returns.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "profile_summary.csv"), index=False, encoding="utf-8-sig")

    with open(os.path.join(out_dir, "profile_config.txt"), "w", encoding="utf-8") as f:
        f.write(f"profile={args.profile}\n")
        f.write(f"top_n={cfg['top_n']}\n")
        f.write(f"min_amount_wan={cfg['min_amount_wan']}\n")
        f.write(f"cost_bps={cfg['cost_bps']}\n")
        for k, v in FIXED_OVERLAY.items():
            f.write(f"{k}={v}\n")

    print(f"profile run完成 -> {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

