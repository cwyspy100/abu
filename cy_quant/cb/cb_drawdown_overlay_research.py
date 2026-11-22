"""回撤约束型仓位管理研究（基于 balanced_premium 基线）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode, eval_ret
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def apply_overlay(
    rets: pd.Series,
    dd_mild: float,
    dd_deep: float,
    exp_mild: float,
    exp_deep: float,
    loss_th: float,
    cooldown_periods: int,
    cooldown_exp: float,
    vol_lookback: int,
    vol_target: float,
    vol_floor: float,
) -> pd.DataFrame:
    """
    对每期收益施加三层风控（仅使用历史信息）：
    1) 回撤分档降仓
    2) 单期大亏后冷却降仓
    3) 近端波动率超阈值时按比例降仓
    """
    if rets.empty:
        return pd.DataFrame(columns=["raw_ret", "exposure", "ret"])

    rows: List[Dict[str, float]] = []
    equity = 1.0
    peak = 1.0
    cooldown_left = 0
    realized: List[float] = []

    for i, raw in enumerate(rets.tolist()):
        dd_prev = equity / peak - 1.0
        exp = 1.0

        # 1) 回撤分档
        if dd_prev <= dd_deep:
            exp = min(exp, exp_deep)
        elif dd_prev <= dd_mild:
            exp = min(exp, exp_mild)

        # 2) 亏损冷却
        if cooldown_left > 0:
            exp = min(exp, cooldown_exp)
            cooldown_left -= 1

        # 3) 波动目标
        if len(realized) >= vol_lookback:
            hist = np.array(realized[-vol_lookback:], dtype=float)
            vol = float(np.nanstd(hist, ddof=1))
            if np.isfinite(vol) and vol > 0 and vol > vol_target:
                exp = min(exp, max(vol_floor, vol_target / vol))

        net = float(raw) * float(exp)
        equity *= (1.0 + net)
        peak = max(peak, equity)
        realized.append(net)

        if raw <= loss_th and cooldown_periods > 0:
            cooldown_left = cooldown_periods

        rows.append({"raw_ret": float(raw), "exposure": float(exp), "ret": net})

    return pd.DataFrame(rows)


def summarize_overlay(ret_df: pd.DataFrame) -> Dict[str, float]:
    if ret_df.empty:
        return {
            "periods": 0,
            "ann_return": np.nan,
            "total_return": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
            "avg_exposure": np.nan,
        }
    s = eval_ret(ret_df["ret"])
    return {
        "periods": int(s["periods"]),
        "ann_return": float(s["ann"]),
        "total_return": float(s["total"]),
        "max_drawdown": float(s["mdd"]),
        "win_rate": float(s["wr"]),
        "avg_exposure": float(ret_df["exposure"].mean()),
    }


def grid_params() -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for dd_mild in (-0.08, -0.10):
        for dd_deep in (-0.14, -0.16):
            if dd_deep >= dd_mild:
                continue
            for exp_mild in (0.85, 0.75):
                for exp_deep in (0.65, 0.50):
                    if exp_deep > exp_mild:
                        continue
                    for loss_th in (-0.03, -0.04):
                        for cooldown_periods in (1, 2):
                            for cooldown_exp in (0.7, 0.5):
                                for vol_target in (0.020, 0.025):
                                    out.append(
                                        {
                                            "dd_mild": dd_mild,
                                            "dd_deep": dd_deep,
                                            "exp_mild": exp_mild,
                                            "exp_deep": exp_deep,
                                            "loss_th": loss_th,
                                            "cooldown_periods": cooldown_periods,
                                            "cooldown_exp": cooldown_exp,
                                            "vol_lookback": 6,
                                            "vol_target": vol_target,
                                            "vol_floor": 0.50,
                                        }
                                    )
    return out


def param_key(p: Dict[str, float]) -> str:
    return (
        f"ddm{p['dd_mild']}_ddd{p['dd_deep']}_em{p['exp_mild']}_ed{p['exp_deep']}"
        f"_lt{p['loss_th']}_cd{int(p['cooldown_periods'])}_ce{p['cooldown_exp']}_vt{p['vol_target']}"
    )


def run_walkforward(
    base_rets: pd.Series,
    candidates: List[Dict[str, float]],
    train_periods: int,
    test_periods: int,
    step: int,
    ann_floor_ratio: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(base_rets)
    folds: List[Dict[str, object]] = []
    oos_base: List[float] = []
    oos_base_exp: List[float] = []
    oos_overlay: List[float] = []
    oos_overlay_exp: List[float] = []

    start = train_periods
    while start + test_periods <= n:
        tr = base_rets.iloc[start - train_periods : start].reset_index(drop=True)
        te = base_rets.iloc[start : start + test_periods].reset_index(drop=True)

        base_tr = summarize_overlay(pd.DataFrame({"ret": tr, "exposure": 1.0}))
        base_te = summarize_overlay(pd.DataFrame({"ret": te, "exposure": 1.0}))

        # 训练集选参：先可行（回撤改善 + 年化不低于底线），再收益优先
        feasible_rows: List[tuple[Dict[str, float], Dict[str, float]]] = []
        scored_rows: List[tuple[Dict[str, float], float, Dict[str, float]]] = []
        for p in candidates:
            over_tr = apply_overlay(tr, **p)
            s = summarize_overlay(over_tr)
            if not np.isfinite(s["ann_return"]) or not np.isfinite(s["max_drawdown"]):
                continue
            metric = s["ann_return"] * 100.0 - abs(s["max_drawdown"]) * 140.0 + s["win_rate"] * 5.0
            scored_rows.append((p, metric, s))
            if (
                s["ann_return"] >= base_tr["ann_return"] * ann_floor_ratio
                and abs(s["max_drawdown"]) < abs(base_tr["max_drawdown"])
            ):
                feasible_rows.append((p, s))

        if feasible_rows:
            feasible_rows.sort(
                key=lambda x: (
                    x[1]["ann_return"],
                    abs(base_tr["max_drawdown"]) - abs(x[1]["max_drawdown"]),
                    x[1]["win_rate"],
                ),
                reverse=True,
            )
            best = feasible_rows[0][0]
            sel_mode = "feasible_first"
        elif scored_rows:
            scored_rows.sort(key=lambda x: x[1], reverse=True)
            best = scored_rows[0][0]
            sel_mode = "score_fallback"
        else:
            break

        over_te = apply_overlay(te, **best)
        s_te = summarize_overlay(over_te)
        oos_base.extend([float(x) for x in te.tolist()])
        oos_base_exp.extend([1.0] * len(te))
        oos_overlay.extend([float(x) for x in over_te["ret"].tolist()])
        oos_overlay_exp.extend([float(x) for x in over_te["exposure"].tolist()])

        folds.append(
            {
                "test_start_idx": int(start),
                "test_end_idx": int(start + test_periods - 1),
                "best_param": param_key(best),
                "selection_mode": sel_mode,
                "base_train_ann": base_tr["ann_return"],
                "base_train_mdd": base_tr["max_drawdown"],
                "overlay_test_ann": s_te["ann_return"],
                "overlay_test_mdd": s_te["max_drawdown"],
                "base_test_ann": base_te["ann_return"],
                "base_test_mdd": base_te["max_drawdown"],
                "delta_test_ann": s_te["ann_return"] - base_te["ann_return"],
                "delta_test_mdd_improve": abs(base_te["max_drawdown"]) - abs(s_te["max_drawdown"]),
            }
        )
        start += step

    base_all = summarize_overlay(pd.DataFrame({"ret": pd.Series(oos_base), "exposure": pd.Series(oos_base_exp)}))
    over_all = summarize_overlay(pd.DataFrame({"ret": pd.Series(oos_overlay), "exposure": pd.Series(oos_overlay_exp)}))
    summary = pd.DataFrame(
        [
            {
                "mode": "base_oos",
                **base_all,
            },
            {
                "mode": "overlay_oos",
                **over_all,
            },
            {
                "mode": "delta_overlay_minus_base",
                "periods": over_all["periods"],
                "ann_return": over_all["ann_return"] - base_all["ann_return"],
                "total_return": over_all["total_return"] - base_all["total_return"],
                "max_drawdown": abs(base_all["max_drawdown"]) - abs(over_all["max_drawdown"]),
                "win_rate": over_all["win_rate"] - base_all["win_rate"],
                "avg_exposure": over_all["avg_exposure"] - base_all["avg_exposure"],
            },
        ]
    )
    return pd.DataFrame(folds), summary


def eval_fixed_oos(
    base_rets: pd.Series,
    param: Dict[str, float],
    train_periods: int,
    test_periods: int,
    step: int,
) -> Dict[str, float]:
    n = len(base_rets)
    start = train_periods
    oos: List[float] = []
    exps: List[float] = []
    while start + test_periods <= n:
        te = base_rets.iloc[start : start + test_periods].reset_index(drop=True)
        ov = apply_overlay(te, **param)
        oos.extend([float(x) for x in ov["ret"].tolist()])
        exps.extend([float(x) for x in ov["exposure"].tolist()])
        start += step
    s = summarize_overlay(pd.DataFrame({"ret": pd.Series(oos), "exposure": pd.Series(exps)}))
    return s


def main() -> None:
    p = argparse.ArgumentParser(description="回撤约束型仓位管理研究（balanced_premium）")
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
    p.add_argument("--ann-floor-ratio", type=float, default=0.85, help="可行参数年化底线，基于基线年化比例")
    p.add_argument("--wf-ann-floor-ratio", type=float, default=0.9, help="walk-forward 训练集可行参数的年化底线比例")
    args = p.parse_args()

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    base_df = run_mode(
        panel=panel,
        mode="balanced_premium",
        top_n=args.top_n,
        min_amount_wan=args.min_amount_wan,
        cost_bps=args.cost_bps,
    ).reset_index(drop=True)
    base_rets = base_df["ret"].astype(float)
    base_stats = summarize_overlay(pd.DataFrame({"ret": base_rets, "exposure": 1.0}))

    # 全样本网格
    rows: List[Dict[str, object]] = []
    cand = grid_params()
    for g in cand:
        over = apply_overlay(base_rets, **g)
        s = summarize_overlay(over)
        row = {**g, **s, "param_key": param_key(g)}
        row["delta_ann"] = row["ann_return"] - base_stats["ann_return"]
        row["delta_mdd_improve"] = abs(base_stats["max_drawdown"]) - abs(row["max_drawdown"])
        row["feasible"] = int(
            np.isfinite(row["ann_return"])
            and np.isfinite(row["max_drawdown"])
            and row["ann_return"] >= base_stats["ann_return"] * float(args.ann_floor_ratio)
            and abs(row["max_drawdown"]) < abs(base_stats["max_drawdown"])
        )
        # 回撤优先评分
        row["score"] = row["delta_mdd_improve"] * 100.0 + row["ann_return"] * 40.0
        rows.append(row)

    grid = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    feasible = grid[grid["feasible"] == 1].copy().sort_values(
        ["delta_mdd_improve", "ann_return"], ascending=[False, False]
    )

    if feasible.empty:
        best = grid.head(1).copy()
    else:
        best = feasible.head(1).copy()

    # OOS walk-forward
    folds, oos_summary = run_walkforward(
        base_rets=base_rets,
        candidates=cand,
        train_periods=args.train_periods,
        test_periods=args.test_periods,
        step=args.step,
        ann_floor_ratio=args.wf_ann_floor_ratio,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_drawdown_overlay_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    grid.to_csv(os.path.join(out_dir, "overlay_grid.csv"), index=False, encoding="utf-8-sig")
    feasible.to_csv(os.path.join(out_dir, "overlay_feasible.csv"), index=False, encoding="utf-8-sig")
    best.to_csv(os.path.join(out_dir, "overlay_best.csv"), index=False, encoding="utf-8-sig")
    folds.to_csv(os.path.join(out_dir, "oos_folds.csv"), index=False, encoding="utf-8-sig")
    oos_summary.to_csv(os.path.join(out_dir, "oos_summary.csv"), index=False, encoding="utf-8-sig")

    base_row = pd.DataFrame([{"mode": "base_full", **base_stats}])
    base_row.to_csv(os.path.join(out_dir, "base_full_summary.csv"), index=False, encoding="utf-8-sig")

    # 固定参数 OOS 对照（避免动态选参噪声）
    target_band = grid[(grid["max_drawdown"] >= -0.15) & (grid["max_drawdown"] <= -0.12)].copy()
    target_band_best = target_band.sort_values("ann_return", ascending=False).head(1) if not target_band.empty else pd.DataFrame()
    mdd_best = grid.sort_values("delta_mdd_improve", ascending=False).head(1)

    fixed_rows: List[Dict[str, object]] = []
    base_oos = oos_summary[oos_summary["mode"] == "base_oos"].iloc[0].to_dict()
    fixed_rows.append(
        {
            "label": "base_oos",
            "param_key": "none",
            "ann_return": base_oos["ann_return"],
            "total_return": base_oos["total_return"],
            "max_drawdown": base_oos["max_drawdown"],
            "win_rate": base_oos["win_rate"],
            "avg_exposure": base_oos["avg_exposure"],
            "delta_ann": 0.0,
            "delta_mdd_improve": 0.0,
        }
    )

    for label, df_sel in [
        ("full_best", best),
        ("target_band_best", target_band_best),
        ("max_mdd_improve_best", mdd_best),
    ]:
        if df_sel is None or df_sel.empty:
            continue
        row = df_sel.iloc[0].to_dict()
        p = {
            "dd_mild": float(row["dd_mild"]),
            "dd_deep": float(row["dd_deep"]),
            "exp_mild": float(row["exp_mild"]),
            "exp_deep": float(row["exp_deep"]),
            "loss_th": float(row["loss_th"]),
            "cooldown_periods": int(row["cooldown_periods"]),
            "cooldown_exp": float(row["cooldown_exp"]),
            "vol_lookback": int(row["vol_lookback"]),
            "vol_target": float(row["vol_target"]),
            "vol_floor": float(row["vol_floor"]),
        }
        s = eval_fixed_oos(
            base_rets=base_rets,
            param=p,
            train_periods=args.train_periods,
            test_periods=args.test_periods,
            step=args.step,
        )
        fixed_rows.append(
            {
                "label": label,
                "param_key": row["param_key"],
                "ann_return": s["ann_return"],
                "total_return": s["total_return"],
                "max_drawdown": s["max_drawdown"],
                "win_rate": s["win_rate"],
                "avg_exposure": s["avg_exposure"],
                "delta_ann": s["ann_return"] - base_oos["ann_return"],
                "delta_mdd_improve": abs(base_oos["max_drawdown"]) - abs(s["max_drawdown"]),
            }
        )

    fixed_oos = pd.DataFrame(fixed_rows)
    fixed_oos.to_csv(os.path.join(out_dir, "fixed_oos_summary.csv"), index=False, encoding="utf-8-sig")

    print(f"回撤约束研究完成 -> {out_dir}")
    print("BASE(full):")
    print(base_row.to_string(index=False))
    print("BEST(full-grid):")
    print(best[["param_key", "ann_return", "total_return", "max_drawdown", "win_rate", "avg_exposure", "delta_ann", "delta_mdd_improve", "feasible"]].to_string(index=False))
    print("OOS summary:")
    print(oos_summary.to_string(index=False))
    print("Fixed OOS summary:")
    print(fixed_oos.to_string(index=False))


if __name__ == "__main__":
    main()
