"""Overlay 动态开关回测：baseline / balanced-overlay / defensive-overlay。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode
from cy_quant.cb.cb_drawdown_overlay_research import apply_overlay, summarize_overlay
from cy_quant.cb.cb_overlay_profile_runner import FIXED_OVERLAY, PROFILES
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def _build_profile(panel: pd.DataFrame, profile: str) -> pd.DataFrame:
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


def _recent_profile_stats(df: pd.DataFrame, profile: str) -> Dict[str, float]:
    b = summarize_overlay(pd.DataFrame({"ret": df[f"base_ret_{profile}"], "exposure": 1.0}))
    o = summarize_overlay(
        pd.DataFrame({"ret": df[f"overlay_ret_{profile}"], "exposure": df[f"overlay_exp_{profile}"]})
    )
    return {
        "profile": profile,
        "delta_ann": float(o["ann_return"] - b["ann_return"]),
        "delta_mdd_improve": float(abs(b["max_drawdown"]) - abs(o["max_drawdown"])),
        "overlay_mdd": float(o["max_drawdown"]),
    }


def _decide_action(
    hist: pd.DataFrame,
    ann_warn: float,
    mdd_warn: float,
    strict_disable: bool,
) -> tuple[str, str]:
    rows = [
        _recent_profile_stats(hist, "balanced"),
        _recent_profile_stats(hist, "defensive"),
    ]
    st = pd.DataFrame(rows)

    ok = st[(st["delta_mdd_improve"] >= mdd_warn) & (st["delta_ann"] >= ann_warn)].copy()
    if not ok.empty:
        best = ok.sort_values(["delta_mdd_improve", "delta_ann"], ascending=[False, False]).iloc[0]
        return f"overlay_{best['profile']}", "keep_overlay"

    if strict_disable and (st["delta_ann"].max() < ann_warn) and (st["delta_mdd_improve"].max() < mdd_warn):
        return "baseline_balanced", "disable_overlay"

    alt = st.sort_values(["overlay_mdd", "delta_ann"], ascending=[False, False]).iloc[0]
    return f"overlay_{alt['profile']}", "review_switch"


def _summ(ret: pd.Series, exp: pd.Series) -> Dict[str, float]:
    s = summarize_overlay(pd.DataFrame({"ret": ret, "exposure": exp}))
    return {
        "periods": int(s["periods"]),
        "ann_return": float(s["ann_return"]),
        "total_return": float(s["total_return"]),
        "max_drawdown": float(s["max_drawdown"]),
        "win_rate": float(s["win_rate"]),
        "avg_exposure": float(s["avg_exposure"]),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Overlay 动态开关回测")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--recent-periods", type=int, default=12)
    p.add_argument("--ann-warn", type=float, default=0.0)
    p.add_argument("--mdd-warn", type=float, default=0.002)
    p.add_argument("--strict-disable", action="store_true")
    p.add_argument("--warmup-mode", choices=["baseline", "overlay_balanced"], default="baseline")
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    pb = _build_profile(panel, "balanced")
    pdv = _build_profile(panel, "defensive")
    if pb.empty or pdv.empty:
        raise RuntimeError("profile 序列构建失败。")

    merged = pb.merge(pdv, on="rebalance_date", how="inner")
    merged = merged.sort_values("rebalance_date").reset_index(drop=True)

    actions: List[Dict[str, object]] = []
    chosen_rets: List[float] = []
    chosen_exp: List[float] = []

    for i in range(len(merged)):
        if i < args.recent_periods:
            if args.warmup_mode == "baseline":
                action = "baseline_balanced"
                reason = "warmup_baseline"
            else:
                action = "overlay_balanced"
                reason = "warmup_overlay"
        else:
            hist = merged.iloc[i - args.recent_periods : i].copy()
            action, reason = _decide_action(
                hist=hist,
                ann_warn=float(args.ann_warn),
                mdd_warn=float(args.mdd_warn),
                strict_disable=bool(args.strict_disable),
            )

        row = merged.iloc[i]
        if action == "baseline_balanced":
            r = float(row["base_ret_balanced"])
            e = 1.0
        elif action == "overlay_balanced":
            r = float(row["overlay_ret_balanced"])
            e = float(row["overlay_exp_balanced"])
        elif action == "overlay_defensive":
            r = float(row["overlay_ret_defensive"])
            e = float(row["overlay_exp_defensive"])
        else:
            raise ValueError(action)

        chosen_rets.append(r)
        chosen_exp.append(e)
        actions.append(
            {
                "rebalance_date": row["rebalance_date"],
                "action": action,
                "reason": reason,
                "ret": r,
                "exposure": e,
            }
        )

    act_df = pd.DataFrame(actions)

    # 对照策略
    base_bal = _summ(merged["base_ret_balanced"], pd.Series([1.0] * len(merged)))
    ov_bal = _summ(merged["overlay_ret_balanced"], merged["overlay_exp_balanced"])
    ov_def = _summ(merged["overlay_ret_defensive"], merged["overlay_exp_defensive"])
    sw = _summ(pd.Series(chosen_rets), pd.Series(chosen_exp))

    summary = pd.DataFrame(
        [
            {"strategy": "base_balanced", **base_bal},
            {"strategy": "overlay_balanced", **ov_bal},
            {"strategy": "overlay_defensive", **ov_def},
            {"strategy": "regime_switch", **sw},
            {
                "strategy": "delta_switch_minus_base",
                "periods": sw["periods"],
                "ann_return": sw["ann_return"] - base_bal["ann_return"],
                "total_return": sw["total_return"] - base_bal["total_return"],
                "max_drawdown": abs(base_bal["max_drawdown"]) - abs(sw["max_drawdown"]),
                "win_rate": sw["win_rate"] - base_bal["win_rate"],
                "avg_exposure": sw["avg_exposure"] - base_bal["avg_exposure"],
            },
        ]
    )

    action_cnt = act_df["action"].value_counts().rename_axis("action").reset_index(name="count")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_overlay_regime_switch_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    act_df.to_csv(os.path.join(out_dir, "switch_actions.csv"), index=False, encoding="utf-8-sig")
    action_cnt.to_csv(os.path.join(out_dir, "switch_action_counts.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "switch_summary.csv"), index=False, encoding="utf-8-sig")

    print(f"regime switch回测完成 -> {out_dir}")
    print(summary.to_string(index=False))
    print("action counts:")
    print(action_cnt.to_string(index=False))


if __name__ == "__main__":
    main()

