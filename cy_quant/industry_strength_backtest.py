#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MA120 二次筛选：行业强度回测（A/B/C 对照）

A: 基线（每月按 total_score 取前N）
B: 行业过滤（每月行业强度 Top30%，再按 total_score 取前N）
C: 混合打分（final_score = 0.7*stock_z + 0.3*industry_z，取前N）
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class Perf:
    strategy: str
    months: int
    total_return: float
    cagr: float
    max_drawdown: float
    avg_monthly_ret: float
    win_rate: float


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def _perf_from_monthly(name: str, monthly: pd.DataFrame) -> Perf:
    if monthly.empty:
        return Perf(name, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mret = monthly["ret_120d_mean"].fillna(0.0)
    equity = (1.0 + mret).cumprod()
    months = len(mret)
    years = months / 12.0
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0
    return Perf(
        strategy=name,
        months=months,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=_max_drawdown(equity),
        avg_monthly_ret=float(mret.mean()),
        win_rate=float((mret > 0).mean()),
    )


def prepare_industry_strength(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["vol_ok_num"] = pd.to_numeric(d["vol_ok"], errors="coerce").fillna(0.0)
    d["rs_top20_num"] = pd.to_numeric(d["rs_top20"], errors="coerce").fillna(0.0)
    d["atr_down_num"] = pd.to_numeric(d["atr_down"], errors="coerce").fillna(0.0)
    d["break_ok_num"] = (
        pd.to_numeric(d["break20"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["break55"], errors="coerce").fillna(0.0)
    )
    d["break_ok_num"] = (d["break_ok_num"] > 0).astype(float)

    agg = (
        d.groupby(["eval_month", "industry"], as_index=False)
        .agg(
            ind_count=("ts_code", "count"),
            ind_ret30_mean=("ret_30d_from_p0", "mean"),
            ind_close_above_mean=("close_above_p0_days", "mean"),
            ind_vol_ok_ratio=("vol_ok_num", "mean"),
            ind_break_ok_ratio=("break_ok_num", "mean"),
            ind_rs_top20_ratio=("rs_top20_num", "mean"),
            ind_atr_down_ratio=("atr_down_num", "mean"),
        )
    )

    agg["industry_strength_raw"] = (
        0.30 * agg["ind_ret30_mean"].fillna(0.0)
        + 0.25 * agg["ind_close_above_mean"].fillna(0.0) / 30.0
        + 0.15 * agg["ind_vol_ok_ratio"].fillna(0.0)
        + 0.15 * agg["ind_break_ok_ratio"].fillna(0.0)
        + 0.15 * agg["ind_rs_top20_ratio"].fillna(0.0)
    )

    agg["industry_strength_score"] = (
        agg.groupby("eval_month")["industry_strength_raw"]
        .rank(method="average", pct=True)
    )
    return agg


def pick_monthly(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    return (
        df.sort_values(["eval_month", "pick_score"], ascending=[True, False])
        .groupby("eval_month", as_index=False)
        .head(top_n)
        .copy()
    )


def monthly_perf(picks: pd.DataFrame, strategy_name: str) -> pd.DataFrame:
    if picks.empty:
        return pd.DataFrame(columns=["eval_month", "strategy", "n", "ret_120d_mean"])
    out = (
        picks.groupby("eval_month", as_index=False)
        .agg(n=("ts_code", "count"), ret_120d_mean=("ret_120d", "mean"))
        .sort_values("eval_month")
    )
    out["strategy"] = strategy_name
    return out


def run_backtest(input_csv: str, output_dir: str, top_n: int, industry_top_pct: float) -> Dict[str, str]:
    df = pd.read_csv(input_csv)
    req = ["ts_code", "industry", "eval_date", "total_score", "ret_120d", "ret_30d_from_p0", "close_above_p0_days"]
    miss = [c for c in req if c not in df.columns]
    if miss:
        raise ValueError(f"input csv missing columns: {miss}")

    df = df.dropna(subset=["industry", "eval_date", "total_score", "ret_120d"]).copy()
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df = df.dropna(subset=["eval_date"])
    df["eval_month"] = df["eval_date"].dt.to_period("M").astype(str)

    ind = prepare_industry_strength(df)
    d = df.merge(ind, on=["eval_month", "industry"], how="left")

    d["pick_score"] = d["total_score"]
    picks_a = pick_monthly(d, top_n)
    m_a = monthly_perf(picks_a, "A_baseline")

    d_b = d[d["industry_strength_score"] >= (1.0 - industry_top_pct)].copy()
    d_b["pick_score"] = d_b["total_score"]
    picks_b = pick_monthly(d_b, top_n)
    m_b = monthly_perf(picks_b, "B_industry_top_filter")

    d_c = d.copy()
    d_c["stock_z"] = d_c.groupby("eval_month")["total_score"].transform(_zscore)
    d_c["industry_z"] = d_c.groupby("eval_month")["industry_strength_score"].transform(_zscore)
    d_c["pick_score"] = 0.7 * d_c["stock_z"] + 0.3 * d_c["industry_z"]
    picks_c = pick_monthly(d_c, top_n)
    m_c = monthly_perf(picks_c, "C_mix_70_30")

    monthly_all = pd.concat([m_a, m_b, m_c], ignore_index=True)
    perf_rows: List[Perf] = [
        _perf_from_monthly("A_baseline", m_a),
        _perf_from_monthly("B_industry_top_filter", m_b),
        _perf_from_monthly("C_mix_70_30", m_c),
    ]
    perf_df = pd.DataFrame([p.__dict__ for p in perf_rows])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"industry_strength_backtest_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    ind.to_csv(os.path.join(out_dir, "industry_strength_monthly.csv"), index=False, encoding="utf-8-sig")
    monthly_all.to_csv(os.path.join(out_dir, "strategy_monthly_perf.csv"), index=False, encoding="utf-8-sig")
    perf_df.to_csv(os.path.join(out_dir, "strategy_overall_perf.csv"), index=False, encoding="utf-8-sig")
    picks_a.to_csv(os.path.join(out_dir, "picks_A_baseline.csv"), index=False, encoding="utf-8-sig")
    picks_b.to_csv(os.path.join(out_dir, "picks_B_industry_top_filter.csv"), index=False, encoding="utf-8-sig")
    picks_c.to_csv(os.path.join(out_dir, "picks_C_mix_70_30.csv"), index=False, encoding="utf-8-sig")

    return {
        "out_dir": out_dir,
        "overall": os.path.join(out_dir, "strategy_overall_perf.csv"),
        "monthly": os.path.join(out_dir, "strategy_monthly_perf.csv"),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="MA120 行业强度回测 A/B/C 对照")
    p.add_argument(
        "--input-csv",
        default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv",
    )
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--industry-top-pct", type=float, default=0.3, help="行业强度前多少比例（如0.3=Top30%）")
    args = p.parse_args()

    res = run_backtest(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        top_n=args.top_n,
        industry_top_pct=args.industry_top_pct,
    )
    print("done")
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
