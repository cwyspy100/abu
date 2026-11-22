"""Overlay 月度健康检查：评估是否继续启用或切换配置。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd

from cy_quant.cb.cb_drawdown_overlay_research import apply_overlay, summarize_overlay
from cy_quant.cb.cb_overlay_profile_runner import PROFILES, FIXED_OVERLAY
from cy_quant.cb.cb_diversification_walkforward_compare import run_mode
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def _run_profile_series(panel: pd.DataFrame, profile: str) -> pd.DataFrame:
    cfg = PROFILES[profile]
    base = run_mode(
        panel=panel,
        mode="balanced_premium",
        top_n=int(cfg["top_n"]),
        min_amount_wan=float(cfg["min_amount_wan"]),
        cost_bps=float(cfg["cost_bps"]),
    ).reset_index(drop=True)
    if base.empty:
        return pd.DataFrame()
    ov = apply_overlay(base["ret"].astype(float).reset_index(drop=True), **FIXED_OVERLAY)
    out = base.copy()
    out["overlay_ret"] = ov["ret"].values
    out["overlay_exposure"] = ov["exposure"].values
    return out


def _stats(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return {"periods": 0, "base_ann": float("nan"), "base_mdd": float("nan"), "overlay_ann": float("nan"), "overlay_mdd": float("nan"), "delta_ann": float("nan"), "delta_mdd_improve": float("nan")}
    b = summarize_overlay(pd.DataFrame({"ret": df["ret"], "exposure": 1.0}))
    o = summarize_overlay(pd.DataFrame({"ret": df["overlay_ret"], "exposure": df["overlay_exposure"]}))
    return {
        "periods": int(len(df)),
        "base_ann": b["ann_return"],
        "base_mdd": b["max_drawdown"],
        "overlay_ann": o["ann_return"],
        "overlay_mdd": o["max_drawdown"],
        "delta_ann": o["ann_return"] - b["ann_return"],
        "delta_mdd_improve": abs(b["max_drawdown"]) - abs(o["max_drawdown"]),
        "overlay_avg_exposure": o["avg_exposure"],
    }


def _recommend(rows: List[Dict[str, float]], ann_warn: float, mdd_warn: float) -> str:
    df = pd.DataFrame(rows)
    if df.empty:
        return "NO_DATA"

    # 按最近窗口优先：先筛选回撤改善达标，再看年化增量
    ok = df[(df["recent_delta_mdd_improve"] >= mdd_warn) & (df["recent_delta_ann"] >= ann_warn)].copy()
    if not ok.empty:
        best = ok.sort_values(["recent_delta_mdd_improve", "recent_delta_ann"], ascending=[False, False]).iloc[0]
        return f"KEEP_OVERLAY profile={best['profile']}"

    # 若所有 profile 都无法满足收益底线，且回撤改善也不显著，则建议暂时关闭 overlay
    if (df["recent_delta_ann"].max() < ann_warn) and (df["recent_delta_mdd_improve"].max() < mdd_warn):
        return "DISABLE_OVERLAY_USE_BASELINE"

    # 若都不达标，选择最近回撤最小的 profile
    alt = df.sort_values(["recent_overlay_mdd", "recent_delta_ann"], ascending=[False, False]).iloc[0]
    return f"REVIEW_OR_SWITCH profile={alt['profile']}"


def main() -> None:
    p = argparse.ArgumentParser(description="Overlay 月度健康检查")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--recent-periods", type=int, default=12)
    p.add_argument("--ann-warn", type=float, default=-0.005, help="最近窗口 overlay 相对 base 年化底线")
    p.add_argument("--mdd-warn", type=float, default=0.005, help="最近窗口回撤改善下限")
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    rows: List[Dict[str, float]] = []
    for profile in sorted(PROFILES.keys()):
        perf = _run_profile_series(panel, profile)
        if perf.empty:
            continue
        full = _stats(perf)
        recent = _stats(perf.tail(int(args.recent_periods)))
        rows.append(
            {
                "profile": profile,
                "full_periods": full["periods"],
                "full_overlay_ann": full["overlay_ann"],
                "full_overlay_mdd": full["overlay_mdd"],
                "full_delta_ann": full["delta_ann"],
                "full_delta_mdd_improve": full["delta_mdd_improve"],
                "recent_periods": recent["periods"],
                "recent_overlay_ann": recent["overlay_ann"],
                "recent_overlay_mdd": recent["overlay_mdd"],
                "recent_delta_ann": recent["delta_ann"],
                "recent_delta_mdd_improve": recent["delta_mdd_improve"],
                "recent_avg_exposure": recent.get("overlay_avg_exposure"),
            }
        )

    out = pd.DataFrame(rows)
    rec = _recommend(rows, ann_warn=float(args.ann_warn), mdd_warn=float(args.mdd_warn))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_overlay_healthcheck_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.to_csv(os.path.join(out_dir, "healthcheck_summary.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "recommendation.txt"), "w", encoding="utf-8") as f:
        f.write(rec + "\n")

    print(f"healthcheck完成 -> {out_dir}")
    print(out.to_string(index=False))
    print(f"recommendation: {rec}")


if __name__ == "__main__":
    main()
