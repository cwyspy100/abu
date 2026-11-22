"""可转债策略自适应风控叠加研究（基于市场溢价环境降仓）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd


def metrics(ret: pd.Series) -> dict:
    if ret.empty:
        return {"periods": 0, "ann_return": np.nan, "total_return": np.nan, "max_drawdown": np.nan, "win_rate": np.nan}
    eq = (1.0 + ret).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(ret)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((ret > 0).mean())
    return {"periods": len(ret), "ann_return": ann, "total_return": total, "max_drawdown": mdd, "win_rate": wr}


def main() -> None:
    p = argparse.ArgumentParser(description="自适应风控叠加研究")
    p.add_argument("--diag-path", default="cy_quant/output/cb_regime_diag_20260527_012117/regime_diag_timeseries.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    args = p.parse_args()

    d = pd.read_csv(args.diag_path)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"])

    base = d["strategy_ret_20d"].astype(float)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_adaptive_overlay_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    # 阈值按样本分位与绝对值混合
    thresholds = sorted(set([32.0, 34.0, 36.0, 38.0, float(d['market_premium_mean'].quantile(0.7)), float(d['market_premium_mean'].quantile(0.8))]))
    exposures = [0.0, 0.3, 0.5, 0.7]

    base_m = metrics(base)
    rows.append({
        "mode": "base",
        "premium_threshold": np.nan,
        "high_regime_exposure": 1.0,
        **base_m,
    })

    for th in thresholds:
        for ex in exposures:
            high = d["market_premium_mean"] >= th
            adj = base.copy()
            adj.loc[high] = adj.loc[high] * ex
            m = metrics(adj)
            rows.append(
                {
                    "mode": "adaptive",
                    "premium_threshold": th,
                    "high_regime_exposure": ex,
                    **m,
                }
            )

    out = pd.DataFrame(rows)
    out["score"] = out["ann_return"] * 100 - out["max_drawdown"].abs() * 80 + out["win_rate"] * 10
    out = out.sort_values("score", ascending=False)

    all_path = os.path.join(out_dir, "adaptive_grid.csv")
    out.to_csv(all_path, index=False, encoding="utf-8-sig")

    best = out.head(1)
    best_path = os.path.join(out_dir, "adaptive_best.csv")
    best.to_csv(best_path, index=False, encoding="utf-8-sig")

    # 给出满足“回撤更小且总收益不低于base-5%”的可行方案
    feasible = out[
        (out["max_drawdown"].abs() <= abs(base_m["max_drawdown"]))
        & (out["total_return"] >= base_m["total_return"] - 0.05)
    ].copy()
    feasible_path = os.path.join(out_dir, "adaptive_feasible.csv")
    feasible.to_csv(feasible_path, index=False, encoding="utf-8-sig")

    print(f"自适应叠加研究完成 -> {out_dir}")
    print("BASE:")
    print(pd.DataFrame([base_m]).to_string(index=False))
    print("\nBEST:")
    print(best.to_string(index=False))


if __name__ == "__main__":
    main()
