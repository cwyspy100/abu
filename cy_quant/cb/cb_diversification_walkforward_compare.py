"""分散约束策略的滚动样本外对照（固定参数，不调参）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_research import pick_top, pick_balanced_premium
from cy_quant.cb.cb_combo_monthly_backtest import calc_period_gross_return, build_trade_path_cache
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def run_mode(
    panel: pd.DataFrame,
    mode: str,
    top_n: int,
    min_amount_wan: float,
    cost_bps: float,
    hold_days: int = 20,
    stop_loss_pct: float | None = None,
    take_half_price: float | None = None,
    take_full_price: float | None = None,
) -> pd.DataFrame:
    d = panel.dropna(subset=["score", "fwd_ret_20d", "trade_date"]).copy()
    d = d[d["amount"] >= min_amount_wan].copy()
    d["month"] = d["trade_date"].dt.to_period("M")
    rebal_dates = d.groupby("month")["trade_date"].max().sort_values().tolist()
    path_cache = build_trade_path_cache(d)

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

        gross, _ = calc_period_gross_return(
            panel=d,
            picks=picks,
            rebalance_date=pd.Timestamp(dt),
            hold_days=hold_days,
            stop_loss_pct=stop_loss_pct,
            take_half_price=take_half_price,
            take_full_price=take_full_price,
            path_cache=path_cache,
        )
        if not np.isfinite(gross):
            continue
        cur = set(picks["ts_code"].astype(str).tolist())
        turn = 1.0 if not prev else 1.0 - len(prev & cur) / float(top_n)
        cost = turn * (cost_bps / 10000.0)
        net = gross - cost
        rows.append({"rebalance_date": pd.to_datetime(dt), "ret": net})
        prev = cur

    return pd.DataFrame(rows)


def eval_ret(ret: pd.Series) -> dict:
    if ret.empty:
        return {"periods": 0, "ann": np.nan, "total": np.nan, "mdd": np.nan, "wr": np.nan}
    eq = (1.0 + ret).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(ret)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((ret > 0).mean())
    return {"periods": len(ret), "ann": ann, "total": total, "mdd": mdd, "wr": wr}


def main() -> None:
    p = argparse.ArgumentParser(description="分散约束 OOS 对照")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument("--min-amount-wan", type=float, default=2000)
    p.add_argument("--cost-bps", type=float, default=40)
    p.add_argument("--train-periods", type=int, default=12)
    p.add_argument("--test-periods", type=int, default=3)
    p.add_argument("--step", type=int, default=3)
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    base = run_mode(panel, "baseline", args.top_n, args.min_amount_wan, args.cost_bps)
    bp = run_mode(panel, "balanced_premium", args.top_n, args.min_amount_wan, args.cost_bps)

    n = min(len(base), len(bp))
    base = base.tail(n).reset_index(drop=True)
    bp = bp.tail(n).reset_index(drop=True)

    folds = []
    base_oos = []
    bp_oos = []

    start = args.train_periods
    while start + args.test_periods <= n:
        te = list(range(start, start + args.test_periods))
        b = base.iloc[te]["ret"].values
        p2 = bp.iloc[te]["ret"].values
        base_oos.extend(list(b))
        bp_oos.extend(list(p2))

        eb = eval_ret(pd.Series(b))
        ep = eval_ret(pd.Series(p2))
        folds.append(
            {
                "test_start": str(base.iloc[te[0]]["rebalance_date"])[:10],
                "test_end": str(base.iloc[te[-1]]["rebalance_date"])[:10],
                "base_total": eb["total"],
                "bp_total": ep["total"],
                "delta_total": ep["total"] - eb["total"],
                "base_ann": eb["ann"],
                "bp_ann": ep["ann"],
                "delta_ann": ep["ann"] - eb["ann"],
            }
        )
        start += args.step

    s_base = eval_ret(pd.Series(base_oos))
    s_bp = eval_ret(pd.Series(bp_oos))

    summary = pd.DataFrame(
        [
            {
                "mode": "baseline_oos",
                "periods": s_base["periods"],
                "ann_return": s_base["ann"],
                "total_return": s_base["total"],
                "max_drawdown": s_base["mdd"],
                "win_rate": s_base["wr"],
            },
            {
                "mode": "balanced_premium_oos",
                "periods": s_bp["periods"],
                "ann_return": s_bp["ann"],
                "total_return": s_bp["total"],
                "max_drawdown": s_bp["mdd"],
                "win_rate": s_bp["wr"],
            },
            {
                "mode": "delta_bp_minus_base",
                "periods": s_bp["periods"],
                "ann_return": s_bp["ann"] - s_base["ann"],
                "total_return": s_bp["total"] - s_base["total"],
                "max_drawdown": abs(s_base["mdd"]) - abs(s_bp["mdd"]),
                "win_rate": s_bp["wr"] - s_base["wr"],
            },
        ]
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_div_wf_compare_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    pd.DataFrame(folds).to_csv(os.path.join(out_dir, "folds.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")

    print(f"分散约束OOS对照完成 -> {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
