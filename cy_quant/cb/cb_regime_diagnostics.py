"""可转债策略失效期诊断：市场状态与策略收益关系。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_combo_monthly_backtest import run_backtest
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def _eq_market_period_return(panel: pd.DataFrame, rebalance_date: pd.Timestamp, horizon: int = 20) -> float:
    d = panel[panel["trade_date"] == rebalance_date].copy()
    if d.empty:
        return np.nan
    col = f"fwd_ret_{horizon}d"
    if col not in d.columns:
        return np.nan
    return float(d[col].dropna().mean()) if d[col].notna().any() else np.nan


def main() -> None:
    p = argparse.ArgumentParser(description="可转债回测环境诊断")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_regime_diag_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    # 以当前主策略配置为诊断对象
    perf, _ = run_backtest(
        panel,
        "combo_dl_trend",
        top_n=25,
        min_amount_wan=2000,
        max_price_for_call_risk=9999.0,
        roundtrip_cost_bps=40.0,
    )
    perf = perf.sort_values("rebalance_date").reset_index(drop=True)

    rows = []
    for r in perf.itertuples(index=False):
        dt = pd.to_datetime(r.rebalance_date)
        cs = panel[panel["trade_date"] == dt]
        rows.append(
            {
                "rebalance_date": dt,
                "strategy_ret_20d": float(r.period_ret_20d),
                "market_eq_ret_20d": _eq_market_period_return(panel, dt, 20),
                "market_premium_mean": float(cs["bond_over_rate"].mean()) if "bond_over_rate" in cs.columns else np.nan,
                "market_premium_std": float(cs["bond_over_rate"].std()) if "bond_over_rate" in cs.columns else np.nan,
                "market_close_mean": float(cs["close"].mean()) if "close" in cs.columns else np.nan,
                "market_cbv_trend_mean": float(cs["stock_trend_120"].mean()) if "stock_trend_120" in cs.columns else np.nan,
            }
        )

    diag = pd.DataFrame(rows).sort_values("rebalance_date").reset_index(drop=True)
    diag["alpha_vs_market"] = diag["strategy_ret_20d"] - diag["market_eq_ret_20d"]
    diag["is_negative"] = diag["strategy_ret_20d"] < 0

    diag_path = os.path.join(out_dir, "regime_diag_timeseries.csv")
    diag.to_csv(diag_path, index=False, encoding="utf-8-sig")

    # 正负期对比
    grp = diag.groupby("is_negative").agg(
        n=("strategy_ret_20d", "size"),
        strategy_ret_mean=("strategy_ret_20d", "mean"),
        market_ret_mean=("market_eq_ret_20d", "mean"),
        alpha_mean=("alpha_vs_market", "mean"),
        premium_mean=("market_premium_mean", "mean"),
        premium_std_mean=("market_premium_std", "mean"),
        close_mean=("market_close_mean", "mean"),
        cbv_trend_mean=("market_cbv_trend_mean", "mean"),
    ).reset_index()
    grp_path = os.path.join(out_dir, "regime_diag_group_summary.csv")
    grp.to_csv(grp_path, index=False, encoding="utf-8-sig")

    # 与市场等权收益相关性
    corr = diag[["strategy_ret_20d", "market_eq_ret_20d", "market_premium_mean", "market_cbv_trend_mean"]].corr()
    corr_path = os.path.join(out_dir, "regime_diag_corr.csv")
    corr.to_csv(corr_path, encoding="utf-8-sig")

    print(f"诊断完成 -> {out_dir}")
    print(grp.to_string(index=False))
    print("\n相关矩阵:")
    print(corr.to_string())


if __name__ == "__main__":
    main()
