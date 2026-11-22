"""联合风控叠加研究：高溢价 + 趋势走弱 条件降仓。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import pandas as pd


def metrics(ret: pd.Series) -> dict:
    eq = (1.0 + ret).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(ret)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((ret > 0).mean())
    return {"total_return": total, "ann_return": ann, "max_drawdown": mdd, "win_rate": wr}


def main() -> None:
    p = argparse.ArgumentParser(description="联合风控叠加研究")
    p.add_argument("--diag-path", default="cy_quant/output/cb_regime_diag_20260527_012117/regime_diag_timeseries.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    args = p.parse_args()

    d = pd.read_csv(args.diag_path)
    base = d["strategy_ret_20d"].astype(float)
    base_m = metrics(base)

    rows = []
    for prem in [34, 36, 38, 40, 42]:
        for tr in [0.05, 0.07, 0.09, 0.11]:
            for ex in [0.0, 0.3, 0.5, 0.7]:
                flag = (d["market_premium_mean"] >= prem) & (d["market_cbv_trend_mean"] <= tr)
                r = base.copy()
                r.loc[flag] = r.loc[flag] * ex
                m = metrics(r)
                rows.append(
                    {
                        "premium_th": prem,
                        "trend_th": tr,
                        "exposure": ex,
                        "flag_n": int(flag.sum()),
                        **m,
                    }
                )

    out = pd.DataFrame(rows)
    out["score"] = out["ann_return"] * 100 - out["max_drawdown"].abs() * 80 + out["win_rate"] * 10

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_joint_overlay_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    out.sort_values("score", ascending=False).to_csv(os.path.join(out_dir, "joint_overlay_grid.csv"), index=False, encoding="utf-8-sig")

    best = out.sort_values("score", ascending=False).head(1)
    best.to_csv(os.path.join(out_dir, "joint_overlay_best.csv"), index=False, encoding="utf-8-sig")

    better_mdd = out[(out["max_drawdown"].abs() < abs(base_m["max_drawdown"])) & (out["ann_return"] >= base_m["ann_return"])]
    better_mdd.to_csv(os.path.join(out_dir, "joint_overlay_better_mdd.csv"), index=False, encoding="utf-8-sig")

    print(f"联合风控研究完成 -> {out_dir}")
    print("BASE:")
    print(pd.DataFrame([base_m]).to_string(index=False))
    print("\nBEST:")
    print(best.to_string(index=False))
    print(f"\n满足更低回撤且不降年化的组合数: {len(better_mdd)}")


if __name__ == "__main__":
    main()
