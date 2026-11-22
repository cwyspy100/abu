"""风险触发切换研究：baseline 与 defensive-overlay 按市场状态切换。"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode, eval_ret
from cy_quant.cb.cb_drawdown_overlay_research import apply_overlay
from cy_quant.cb.cb_overlay_profile_runner import FIXED_OVERLAY
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


@dataclass
class TriggerParam:
    lookback: int
    z_prem: float
    z_close: float
    mkt_ret_th: float
    trend_th: float
    cooldown: int

    @property
    def key(self) -> str:
        return (
            f"lb{self.lookback}_zp{self.z_prem}_zc{self.z_close}"
            f"_mr{self.mkt_ret_th}_tr{self.trend_th}_cd{self.cooldown}"
        )


def _market_snapshot(panel: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    rows = []
    for d in dates:
        cs = panel[panel["trade_date"] == d]
        if cs.empty:
            continue
        rows.append(
            {
                "rebalance_date": pd.to_datetime(d),
                "mkt_premium_mean": float(cs["bond_over_rate"].mean()),
                "mkt_close_mean": float(cs["close"].mean()),
                "mkt_trend_mean": float(cs["stock_trend_120"].mean()),
                "mkt_ret20_mean": float(cs["fwd_ret_20d"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("rebalance_date").reset_index(drop=True)


def _build_series(panel: pd.DataFrame) -> pd.DataFrame:
    # baseline
    base = run_mode(panel, "balanced_premium", top_n=25, min_amount_wan=2000, cost_bps=40).copy()
    # defensive (先生成候选池收益，再叠加固定 overlay)
    de = run_mode(panel, "balanced_premium", top_n=15, min_amount_wan=1500, cost_bps=40).copy()
    base = base.sort_values("rebalance_date").reset_index(drop=True)
    de = de.sort_values("rebalance_date").reset_index(drop=True)
    de_ov = apply_overlay(de["ret"].astype(float).reset_index(drop=True), **FIXED_OVERLAY)

    base = base.rename(columns={"ret": "base_ret"})
    de["defensive_base_ret"] = de["ret"]
    de["defensive_overlay_ret"] = de_ov["ret"].values
    de["defensive_overlay_exp"] = de_ov["exposure"].values

    out = base.merge(
        de[["rebalance_date", "defensive_base_ret", "defensive_overlay_ret", "defensive_overlay_exp"]],
        on="rebalance_date",
        how="inner",
    )
    out = out.sort_values("rebalance_date").reset_index(drop=True)

    snap = _market_snapshot(panel, out["rebalance_date"])
    out = out.merge(snap, on="rebalance_date", how="left")
    return out


def _zscore(hist: pd.Series, v: float) -> float:
    if len(hist) < 2:
        return np.nan
    m = float(hist.mean())
    s = float(hist.std(ddof=1))
    if not np.isfinite(s) or s <= 1e-12:
        return 0.0
    return (float(v) - m) / s


def simulate_switch(df: pd.DataFrame, p: TriggerParam, idx: pd.Index | None = None) -> pd.DataFrame:
    d = df.copy()
    if idx is not None:
        d = d.iloc[idx].copy().reset_index(drop=True)
    if d.empty:
        return pd.DataFrame(columns=["rebalance_date", "ret", "mode", "trigger"])

    rows = []
    cooldown_left = 0
    for i in range(len(d)):
        row = d.iloc[i]
        trigger = False
        if i >= p.lookback:
            h = d.iloc[i - p.lookback : i]
            z_prem = _zscore(h["mkt_premium_mean"], row["mkt_premium_mean"])
            z_close = _zscore(h["mkt_close_mean"], row["mkt_close_mean"])
            cond_vol = (z_prem >= p.z_prem) and (z_close >= p.z_close)
            cond_mkt = float(row["mkt_ret20_mean"]) <= p.mkt_ret_th
            cond_trend = float(row["mkt_trend_mean"]) <= p.trend_th
            trigger = bool(cond_vol or cond_mkt or cond_trend)

        if cooldown_left > 0:
            mode = "defensive_overlay"
            ret = float(row["defensive_overlay_ret"])
            cooldown_left -= 1
        elif trigger:
            mode = "defensive_overlay"
            ret = float(row["defensive_overlay_ret"])
            cooldown_left = max(int(p.cooldown) - 1, 0)
        else:
            mode = "baseline"
            ret = float(row["base_ret"])

        rows.append(
            {
                "rebalance_date": row["rebalance_date"],
                "ret": ret,
                "mode": mode,
                "trigger": int(trigger),
            }
        )
    return pd.DataFrame(rows)


def _summary(ret: pd.Series) -> Dict[str, float]:
    s = eval_ret(ret)
    return {
        "periods": int(s["periods"]),
        "ann_return": float(s["ann"]),
        "total_return": float(s["total"]),
        "max_drawdown": float(s["mdd"]),
        "win_rate": float(s["wr"]),
    }


def _score(ann: float, mdd: float, wr: float) -> float:
    if not np.isfinite(ann) or not np.isfinite(mdd) or not np.isfinite(wr):
        return -1e18
    return ann * 100.0 - abs(mdd) * 90.0 + wr * 8.0


def param_grid() -> List[TriggerParam]:
    out: List[TriggerParam] = []
    for lb in [6, 9, 12]:
        for zp in [0.5, 1.0, 1.5]:
            for zc in [0.5, 1.0, 1.5]:
                for mr in [0.0, -0.005]:
                    for tr in [0.0, -0.01]:
                        for cd in [1, 2, 3]:
                            out.append(
                                TriggerParam(
                                    lookback=lb,
                                    z_prem=zp,
                                    z_close=zc,
                                    mkt_ret_th=mr,
                                    trend_th=tr,
                                    cooldown=cd,
                                )
                            )
    return out


def walkforward_select(df: pd.DataFrame, params: List[TriggerParam], train_periods: int, test_periods: int, step: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(df)
    folds = []
    oos = []
    base_oos = []
    def_oos = []

    start = train_periods
    while start + test_periods <= n:
        tr_idx = list(range(start - train_periods, start))
        te_idx = list(range(start, start + test_periods))

        base_tr = _summary(df.iloc[tr_idx]["base_ret"])
        best_p = None
        best_s = -1e18
        best_tr = None
        for p in params:
            tr = simulate_switch(df, p, tr_idx)
            st = _summary(tr["ret"])
            # 训练集：优先回撤改善 + 收益不过分牺牲
            mdd_imp = abs(base_tr["max_drawdown"]) - abs(st["max_drawdown"])
            ann_floor = st["ann_return"] >= base_tr["ann_return"] * 0.92
            if not ann_floor:
                continue
            sc = _score(st["ann_return"], st["max_drawdown"], st["win_rate"]) + mdd_imp * 50.0
            if sc > best_s:
                best_s = sc
                best_p = p
                best_tr = st

        if best_p is None:
            # fallback: 不切换，直接 baseline
            best_p = TriggerParam(lookback=6, z_prem=9.9, z_close=9.9, mkt_ret_th=-9.9, trend_th=-9.9, cooldown=1)
            best_tr = base_tr

        te = simulate_switch(df, best_p, te_idx)
        te_s = _summary(te["ret"])
        base_te = _summary(df.iloc[te_idx]["base_ret"])
        def_te = _summary(df.iloc[te_idx]["defensive_overlay_ret"])

        oos.extend(te["ret"].tolist())
        base_oos.extend(df.iloc[te_idx]["base_ret"].tolist())
        def_oos.extend(df.iloc[te_idx]["defensive_overlay_ret"].tolist())

        folds.append(
            {
                "test_start": str(df.iloc[te_idx[0]]["rebalance_date"])[:10],
                "test_end": str(df.iloc[te_idx[-1]]["rebalance_date"])[:10],
                "best_param": best_p.key,
                "test_ann": te_s["ann_return"],
                "test_mdd": te_s["max_drawdown"],
                "base_test_ann": base_te["ann_return"],
                "base_test_mdd": base_te["max_drawdown"],
                "def_test_ann": def_te["ann_return"],
                "def_test_mdd": def_te["max_drawdown"],
            }
        )
        start += step

    sw = _summary(pd.Series(oos))
    bs = _summary(pd.Series(base_oos))
    ds = _summary(pd.Series(def_oos))
    summary = pd.DataFrame(
        [
            {"mode": "switch_oos", **sw},
            {"mode": "base_oos", **bs},
            {"mode": "defensive_oos", **ds},
            {
                "mode": "delta_switch_minus_base",
                "periods": sw["periods"],
                "ann_return": sw["ann_return"] - bs["ann_return"],
                "total_return": sw["total_return"] - bs["total_return"],
                "max_drawdown": abs(bs["max_drawdown"]) - abs(sw["max_drawdown"]),
                "win_rate": sw["win_rate"] - bs["win_rate"],
            },
        ]
    )
    return pd.DataFrame(folds), summary


def main() -> None:
    p = argparse.ArgumentParser(description="风险触发切换研究")
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
    series_df = _build_series(panel)

    # 全样本网格
    base_full = _summary(series_df["base_ret"])
    rows = []
    for prm in param_grid():
        sim = simulate_switch(series_df, prm)
        s = _summary(sim["ret"])
        c = sim["mode"].value_counts()
        rows.append(
            {
                "param_key": prm.key,
                "lookback": prm.lookback,
                "z_prem": prm.z_prem,
                "z_close": prm.z_close,
                "mkt_ret_th": prm.mkt_ret_th,
                "trend_th": prm.trend_th,
                "cooldown": prm.cooldown,
                **s,
                "delta_ann": s["ann_return"] - base_full["ann_return"],
                "delta_mdd_improve": abs(base_full["max_drawdown"]) - abs(s["max_drawdown"]),
                "baseline_count": int(c.get("baseline", 0)),
                "defensive_count": int(c.get("defensive_overlay", 0)),
            }
        )
    grid = pd.DataFrame(rows)
    grid["score"] = grid["delta_mdd_improve"] * 100.0 + grid["ann_return"] * 30.0
    grid = grid.sort_values(["score", "delta_ann"], ascending=[False, False]).reset_index(drop=True)

    # OOS walk-forward select
    folds, wf_summary = walkforward_select(
        series_df,
        param_grid(),
        train_periods=args.train_periods,
        test_periods=args.test_periods,
        step=args.step,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_risk_switch_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    grid.to_csv(os.path.join(out_dir, "risk_switch_grid.csv"), index=False, encoding="utf-8-sig")
    folds.to_csv(os.path.join(out_dir, "risk_switch_wf_folds.csv"), index=False, encoding="utf-8-sig")
    wf_summary.to_csv(os.path.join(out_dir, "risk_switch_wf_summary.csv"), index=False, encoding="utf-8-sig")

    print(f"风险触发切换研究完成 -> {out_dir}")
    print("WF summary:")
    print(wf_summary.to_string(index=False))
    print("Top full-sample params:")
    print(
        grid[
            [
                "param_key",
                "ann_return",
                "max_drawdown",
                "delta_ann",
                "delta_mdd_improve",
                "baseline_count",
                "defensive_count",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

