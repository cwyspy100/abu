"""可转债策略波动率目标仓位研究（基于滞后市场波动）。"""

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
    p = argparse.ArgumentParser(description="波动率目标仓位研究")
    p.add_argument("--diag-path", default="cy_quant/output/cb_regime_diag_20260527_012117/regime_diag_timeseries.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    args = p.parse_args()

    d = pd.read_csv(args.diag_path)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"])
    d = d.sort_values("rebalance_date").reset_index(drop=True)

    base = d["strategy_ret_20d"].astype(float)
    mkt = d["market_eq_ret_20d"].astype(float)

    base_m = metrics(base)
    rows = []

    for lb in [3, 4, 6]:
        vol = mkt.rolling(lb).std().shift(1)
        for q in [0.6, 0.7, 0.8]:
            th = float(vol.quantile(q))
            for ex in [0.3, 0.5, 0.7]:
                r = base.copy()
                high = vol >= th
                r.loc[high] = r.loc[high] * ex
                m = metrics(r)
                rows.append(
                    {
                        "lookback": lb,
                        "vol_quantile": q,
                        "vol_threshold": th,
                        "high_vol_exposure": ex,
                        "high_vol_n": int(high.fillna(False).sum()),
                        **m,
                    }
                )

    out = pd.DataFrame(rows)
    out["score"] = out["ann_return"] * 100 - out["max_drawdown"].abs() * 80 + out["win_rate"] * 10

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_vol_overlay_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.sort_values("score", ascending=False).to_csv(os.path.join(out_dir, "vol_overlay_grid.csv"), index=False, encoding="utf-8-sig")

    best = out.sort_values("score", ascending=False).head(1)
    best.to_csv(os.path.join(out_dir, "vol_overlay_best.csv"), index=False, encoding="utf-8-sig")

    # 更注重风控：回撤更低且年化不低于base的95%
    feasible = out[(out["max_drawdown"].abs() < abs(base_m["max_drawdown"])) & (out["ann_return"] >= base_m["ann_return"] * 0.95)]
    feasible.to_csv(os.path.join(out_dir, "vol_overlay_feasible.csv"), index=False, encoding="utf-8-sig")

    print(f"波动率叠加研究完成 -> {out_dir}")
    print("BASE:")
    print(pd.DataFrame([base_m]).to_string(index=False))
    print("\nBEST:")
    print(best.to_string(index=False))
    print(f"\n风控可行组合数: {len(feasible)}")


if __name__ == "__main__":
    main()
