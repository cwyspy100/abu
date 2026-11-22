"""Overlay 实盘决策脚本：输出当前动作建议 + 依据 + 风险快照。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode
from cy_quant.cb.cb_drawdown_overlay_research import apply_overlay, summarize_overlay
from cy_quant.cb.cb_overlay_profile_runner import PROFILES, FIXED_OVERLAY
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def _profile_series(panel: pd.DataFrame, profile: str) -> pd.DataFrame:
    cfg = PROFILES[profile]
    base = run_mode(
        panel=panel,
        mode="balanced_premium",
        top_n=int(cfg["top_n"]),
        min_amount_wan=float(cfg["min_amount_wan"]),
        cost_bps=float(cfg["cost_bps"]),
    ).copy()
    if base.empty:
        return pd.DataFrame()
    base = base.sort_values("rebalance_date").reset_index(drop=True)
    ov = apply_overlay(base["ret"].astype(float).reset_index(drop=True), **FIXED_OVERLAY)
    base = base.rename(columns={"ret": f"base_ret_{profile}"})
    base[f"overlay_ret_{profile}"] = ov["ret"].values
    base[f"overlay_exp_{profile}"] = ov["exposure"].values
    return base


def _stats(base_ret: pd.Series, overlay_ret: pd.Series, overlay_exp: pd.Series) -> Dict[str, float]:
    b = summarize_overlay(pd.DataFrame({"ret": base_ret, "exposure": 1.0}))
    o = summarize_overlay(pd.DataFrame({"ret": overlay_ret, "exposure": overlay_exp}))
    return {
        "base_ann": float(b["ann_return"]),
        "base_mdd": float(b["max_drawdown"]),
        "overlay_ann": float(o["ann_return"]),
        "overlay_mdd": float(o["max_drawdown"]),
        "delta_ann": float(o["ann_return"] - b["ann_return"]),
        "delta_mdd_improve": float(abs(b["max_drawdown"]) - abs(o["max_drawdown"])),
        "overlay_avg_exposure": float(o["avg_exposure"]),
    }


def _decision_from_recent(
    rows: List[Dict[str, float]],
    ann_warn: float,
    mdd_warn: float,
    strict_disable: bool,
) -> tuple[str, str]:
    df = pd.DataFrame(rows)
    if df.empty:
        return "NO_DATA", "无可用数据"

    ok = df[(df["recent_delta_mdd_improve"] >= mdd_warn) & (df["recent_delta_ann"] >= ann_warn)].copy()
    if not ok.empty:
        best = ok.sort_values(["recent_delta_mdd_improve", "recent_delta_ann"], ascending=[False, False]).iloc[0]
        return f"KEEP_OVERLAY_{best['profile'].upper()}", "最近窗口满足收益与回撤双阈值"

    if strict_disable and (df["recent_delta_ann"].max() < ann_warn) and (df["recent_delta_mdd_improve"].max() < mdd_warn):
        return "USE_BASELINE", "最近窗口两档 overlay 均未满足阈值，触发严格回退"

    alt = df.sort_values(["recent_overlay_mdd", "recent_delta_ann"], ascending=[False, False]).iloc[0]
    return f"SWITCH_TO_{alt['profile'].upper()}", "最近窗口未双达标，切至相对更稳档位"


def main() -> None:
    p = argparse.ArgumentParser(description="Overlay 实盘决策脚本")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--recent-periods", type=int, default=12)
    p.add_argument("--ann-warn", type=float, default=0.0)
    p.add_argument("--mdd-warn", type=float, default=0.002)
    p.add_argument("--strict-disable", action="store_true")
    p.add_argument("--decision-name", default="default")
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    pb = _profile_series(panel, "balanced")
    pdv = _profile_series(panel, "defensive")
    if pb.empty or pdv.empty:
        raise RuntimeError("无法构建 profile 收益序列。")

    merged = pb.merge(pdv, on="rebalance_date", how="inner").sort_values("rebalance_date").reset_index(drop=True)
    recent = merged.tail(int(args.recent_periods)).copy()

    full_bal = _stats(merged["base_ret_balanced"], merged["overlay_ret_balanced"], merged["overlay_exp_balanced"])
    full_def = _stats(merged["base_ret_defensive"], merged["overlay_ret_defensive"], merged["overlay_exp_defensive"])
    rec_bal = _stats(recent["base_ret_balanced"], recent["overlay_ret_balanced"], recent["overlay_exp_balanced"])
    rec_def = _stats(recent["base_ret_defensive"], recent["overlay_ret_defensive"], recent["overlay_exp_defensive"])

    rows = [
        {
            "profile": "balanced",
            "full_delta_ann": full_bal["delta_ann"],
            "full_delta_mdd_improve": full_bal["delta_mdd_improve"],
            "recent_delta_ann": rec_bal["delta_ann"],
            "recent_delta_mdd_improve": rec_bal["delta_mdd_improve"],
            "recent_overlay_mdd": rec_bal["overlay_mdd"],
            "recent_overlay_ann": rec_bal["overlay_ann"],
            "recent_overlay_avg_exposure": rec_bal["overlay_avg_exposure"],
        },
        {
            "profile": "defensive",
            "full_delta_ann": full_def["delta_ann"],
            "full_delta_mdd_improve": full_def["delta_mdd_improve"],
            "recent_delta_ann": rec_def["delta_ann"],
            "recent_delta_mdd_improve": rec_def["delta_mdd_improve"],
            "recent_overlay_mdd": rec_def["overlay_mdd"],
            "recent_overlay_ann": rec_def["overlay_ann"],
            "recent_overlay_avg_exposure": rec_def["overlay_avg_exposure"],
        },
    ]
    eval_df = pd.DataFrame(rows)

    action, reason = _decision_from_recent(
        rows=rows,
        ann_warn=float(args.ann_warn),
        mdd_warn=float(args.mdd_warn),
        strict_disable=bool(args.strict_disable),
    )

    latest_date = pd.to_datetime(merged["rebalance_date"].iloc[-1]).strftime("%Y-%m-%d")
    decision = pd.DataFrame(
        [
            {
                "decision_name": args.decision_name,
                "asof_rebalance_date": latest_date,
                "recent_periods": int(args.recent_periods),
                "ann_warn": float(args.ann_warn),
                "mdd_warn": float(args.mdd_warn),
                "strict_disable": bool(args.strict_disable),
                "action": action,
                "reason": reason,
            }
        ]
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_live_decision_{args.decision_name}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    eval_df.to_csv(os.path.join(out_dir, "profile_eval.csv"), index=False, encoding="utf-8-sig")
    decision.to_csv(os.path.join(out_dir, "decision.csv"), index=False, encoding="utf-8-sig")

    with open(os.path.join(out_dir, "decision_text.txt"), "w", encoding="utf-8") as f:
        f.write(f"action={action}\n")
        f.write(f"reason={reason}\n")
        f.write(f"asof_rebalance_date={latest_date}\n")
        f.write(f"recent_periods={args.recent_periods}\n")
        f.write(f"ann_warn={args.ann_warn}\n")
        f.write(f"mdd_warn={args.mdd_warn}\n")
        f.write(f"strict_disable={bool(args.strict_disable)}\n")

    print(f"live decision完成 -> {out_dir}")
    print(decision.to_string(index=False))
    print("profile eval:")
    print(eval_df.to_string(index=False))


if __name__ == "__main__":
    main()

