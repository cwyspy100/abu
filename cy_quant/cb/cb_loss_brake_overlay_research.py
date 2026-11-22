"""策略亏损触发降仓研究（下一期仓位刹车）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd


def metrics(ret: pd.Series) -> dict:
    eq = (1.0 + ret).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(ret)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((ret > 0).mean())
    return {"total_return": total, "ann_return": ann, "max_drawdown": mdd, "win_rate": wr}


def main() -> None:
    p = argparse.ArgumentParser(description="亏损触发降仓研究")
    p.add_argument("--diag-path", default="cy_quant/output/cb_regime_diag_20260527_012117/regime_diag_timeseries.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    args = p.parse_args()

    d = pd.read_csv(args.diag_path)
    base = d["strategy_ret_20d"].astype(float).reset_index(drop=True)
    base_m = metrics(base)

    rows = []
    prev = base.shift(1)
    for th in [-0.03, -0.025, -0.02, -0.015, -0.01]:
        for ex in [0.0, 0.3, 0.5, 0.7]:
            flag = prev <= th
            r = base.copy()
            r.loc[flag] = r.loc[flag] * ex
            m = metrics(r)
            rows.append({"loss_th": th, "next_exposure": ex, "flag_n": int(flag.fillna(False).sum()), **m})

    out = pd.DataFrame(rows)
    out["score"] = out["ann_return"] * 100 - out["max_drawdown"].abs() * 80 + out["win_rate"] * 10

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_loss_brake_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.sort_values("score", ascending=False).to_csv(os.path.join(out_dir, "loss_brake_grid.csv"), index=False, encoding="utf-8-sig")

    better = out[(out["max_drawdown"].abs() < abs(base_m["max_drawdown"])) & (out["ann_return"] >= base_m["ann_return"] * 0.95)]
    better.to_csv(os.path.join(out_dir, "loss_brake_better.csv"), index=False, encoding="utf-8-sig")

    print(f"亏损刹车研究完成 -> {out_dir}")
    print("BASE:")
    print(pd.DataFrame([base_m]).to_string(index=False))
    print(f"\n满足更低回撤且年化>=基线95%的组合数: {len(better)}")


if __name__ == "__main__":
    main()
