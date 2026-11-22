"""可转债策略时间稳定性研究：分段 + 滚动窗口。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_combo_monthly_backtest import run_backtest, summarize


def _summ_from_perf(perf: pd.DataFrame) -> Dict[str, float]:
    s = summarize(perf)
    total_ret = float((1.0 + perf["period_ret_20d"]).prod() - 1.0) if not perf.empty else np.nan
    return {
        "periods": s.get("periods", np.nan),
        "ann_return": s.get("ann_return", np.nan),
        "total_return": total_ret,
        "max_drawdown": s.get("max_drawdown", np.nan),
        "win_rate": s.get("win_rate", np.nan),
        "avg_period_ret": s.get("avg_period_ret", np.nan),
    }


def _split_perf(perf: pd.DataFrame) -> pd.DataFrame:
    if perf.empty:
        return pd.DataFrame()
    n = len(perf)
    mid = n // 2
    chunks = {
        "first_half": perf.iloc[:mid].copy(),
        "second_half": perf.iloc[mid:].copy(),
    }
    rows = []
    for name, sub in chunks.items():
        s = _summ_from_perf(sub)
        s["segment"] = name
        rows.append(s)
    return pd.DataFrame(rows)


def _yearly_perf(perf: pd.DataFrame) -> pd.DataFrame:
    if perf.empty:
        return pd.DataFrame()
    out_rows: List[Dict[str, float]] = []
    d = perf.copy()
    d["year"] = pd.to_datetime(d["rebalance_date"]).dt.year
    for y, g in d.groupby("year"):
        s = _summ_from_perf(g)
        s["year"] = int(y)
        out_rows.append(s)
    return pd.DataFrame(out_rows).sort_values("year")


def _rolling_perf(perf: pd.DataFrame, window: int = 6) -> pd.DataFrame:
    if perf.empty or len(perf) < window:
        return pd.DataFrame()
    rows: List[Dict[str, float]] = []
    for i in range(window - 1, len(perf)):
        sub = perf.iloc[i - window + 1 : i + 1].copy()
        s = _summ_from_perf(sub)
        s["window"] = window
        s["end_rebalance_date"] = sub["rebalance_date"].iloc[-1]
        rows.append(s)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="可转债组合策略时间稳定性研究")
    parser.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    parser.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    parser.add_argument("--out-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--min-amount-wan", type=float, default=3000.0)
    parser.add_argument("--max-price-for-call-risk", type=float, default=140.0)
    parser.add_argument("--roundtrip-cost-bps", type=float, default=40.0)
    parser.add_argument("--rolling-window", type=int, default=6)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_stability_research_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_panel(args.cb_daily, args.cb_basic)
    panel = build_combo_factors(panel)

    strategies = ["combo_dl_trend", "combo_dl_trend_call", "combo_lp_trend"]

    full_rows = []
    split_rows = []
    for st in strategies:
        perf, holds = run_backtest(
            panel,
            st,
            top_n=args.top_n,
            min_amount_wan=args.min_amount_wan,
            max_price_for_call_risk=args.max_price_for_call_risk,
            roundtrip_cost_bps=args.roundtrip_cost_bps,
        )

        perf_path = os.path.join(out_dir, f"perf_{st}.csv")
        holds_path = os.path.join(out_dir, f"holds_{st}.csv")
        perf.to_csv(perf_path, index=False, encoding="utf-8-sig")
        holds.to_csv(holds_path, index=False, encoding="utf-8-sig")

        full = _summ_from_perf(perf)
        full["strategy"] = st
        full_rows.append(full)

        sp = _split_perf(perf)
        if not sp.empty:
            sp["strategy"] = st
            split_rows.append(sp)

        yr = _yearly_perf(perf)
        if not yr.empty:
            yr["strategy"] = st
            yr.to_csv(os.path.join(out_dir, f"yearly_{st}.csv"), index=False, encoding="utf-8-sig")

        roll = _rolling_perf(perf, window=args.rolling_window)
        if not roll.empty:
            roll["strategy"] = st
            roll.to_csv(os.path.join(out_dir, f"rolling_{st}.csv"), index=False, encoding="utf-8-sig")

    full_df = pd.DataFrame(full_rows)
    full_df = full_df[["strategy", "periods", "ann_return", "total_return", "max_drawdown", "win_rate", "avg_period_ret"]]
    full_df.to_csv(os.path.join(out_dir, "stability_full_summary.csv"), index=False, encoding="utf-8-sig")

    if split_rows:
        split_df = pd.concat(split_rows, ignore_index=True)
        split_df = split_df[["strategy", "segment", "periods", "ann_return", "total_return", "max_drawdown", "win_rate", "avg_period_ret"]]
        split_df.to_csv(os.path.join(out_dir, "stability_split_summary.csv"), index=False, encoding="utf-8-sig")

    print(f"稳定性研究完成 -> {out_dir}")
    print(f"full summary -> {os.path.join(out_dir, 'stability_full_summary.csv')}")


if __name__ == "__main__":
    main()
