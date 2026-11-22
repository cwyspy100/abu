"""可转债月度停止/恢复交易规则研究。

规则在每个调仓日产生，只使用当日指数与上一个已完成持有期的策略收益，
避免把当期收益用于当期的仓位判断。
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import eval_ret


DEFAULT_INDEX_PATHS = [
    "/Users/water/abu/data/csv/astock/sh000852_20140708_20250309",
    "/Users/water/abu/data/csv/sh000852_20240126_20260314",
    "/Users/water/abu/data/csv/sh000852_20260314_20260903.csv",
]


def load_index(paths: list[str], ma_window: int) -> pd.DataFrame:
    """合并中证1000历史文件，并基于收盘价计算只依赖历史的均线信号。"""
    parts = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        d = pd.read_csv(path)
        if "trade_date" in d.columns:
            d["trade_date"] = pd.to_datetime(d["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        elif "date" in d.columns:
            d["trade_date"] = pd.to_datetime(d["date"].astype(str), format="%Y%m%d", errors="coerce")
        else:
            continue
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        parts.append(d[["trade_date", "close"]].dropna())
    if not parts:
        raise FileNotFoundError("未找到可用的中证1000指数数据")
    out = pd.concat(parts, ignore_index=True).sort_values("trade_date")
    out = out.drop_duplicates("trade_date", keep="last").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(ma_window, min_periods=ma_window).mean()
    out["index_risk_on"] = out["close"] > out["ma120"]
    return out


def apply_gate(
    perf: pd.DataFrame,
    index: pd.DataFrame,
    use_index: bool,
    loss_threshold: float | None,
    loss_exposure: float,
) -> pd.DataFrame:
    """根据调仓日指数与上期收益计算本期仓位，不读取本期收益。"""
    out = perf.sort_values("rebalance_date").copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"])
    out = pd.merge_asof(
        out,
        index[["trade_date", "close", "ma120", "index_risk_on"]].sort_values("trade_date"),
        left_on="rebalance_date",
        right_on="trade_date",
        direction="backward",
    )
    out["index_risk_on"] = out["index_risk_on"].fillna(False)
    out["previous_ret"] = out["ret"].shift(1)
    out["loss_brake"] = False if loss_threshold is None else out["previous_ret"] <= loss_threshold

    exposure = pd.Series(1.0, index=out.index)
    if use_index:
        exposure = exposure.where(out["index_risk_on"], 0.0)
    if loss_threshold is not None:
        exposure = exposure.where(~out["loss_brake"], np.minimum(exposure, loss_exposure))
    out["exposure"] = exposure
    out["gated_ret"] = out["ret"] * out["exposure"]
    return out


def apply_shadow_recovery(perf: pd.DataFrame, stop_threshold: float, resume_threshold: float) -> pd.DataFrame:
    """亏损后停实盘、保留影子组合，影子单期转强后次期恢复实盘。"""
    out = perf.sort_values("rebalance_date").copy().reset_index(drop=True)
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"])
    active = True
    rows = []
    for row in out.itertuples(index=False):
        virtual_ret = float(row.ret)
        exposure = 1.0 if active else 0.0
        action = "trade" if active else "shadow"
        actual_ret = virtual_ret * exposure

        # 本期结束时才能看到虚拟组合收益，状态从下一期生效。
        if active and virtual_ret <= stop_threshold:
            next_active = False
            next_action = "pause_after_loss"
        elif not active and virtual_ret >= resume_threshold:
            next_active = True
            next_action = "resume_after_shadow_gain"
        else:
            next_active = active
            next_action = "keep"
        rows.append(
            {
                "rebalance_date": row.rebalance_date,
                "ret": virtual_ret,
                "exposure": exposure,
                "gated_ret": actual_ret,
                "state": action,
                "next_action": next_action,
            }
        )
        active = next_active
    return pd.DataFrame(rows)


def yearly(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, g in df.groupby(df["rebalance_date"].dt.year):
        m = eval_ret(g["gated_ret"].reset_index(drop=True))
        rows.append({"year": int(year), "periods": int(len(g)), "return": m["total"], "win_rate": m["wr"], "avg_exposure": float(g["exposure"].mean())})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="可转债月度停止/恢复交易规则研究")
    parser.add_argument("--period-returns", required=True, help="基线月度收益 CSV，需含 rebalance_date、ret")
    parser.add_argument("--index-path", action="append", default=[], help="中证1000 CSV；可重复指定")
    parser.add_argument("--ma-window", type=int, default=120)
    parser.add_argument("--out-dir", default="cy_quant/output")
    args = parser.parse_args()

    perf = pd.read_csv(args.period_returns)
    if not {"rebalance_date", "ret"}.issubset(perf.columns):
        raise ValueError("period-returns 必须包含 rebalance_date 和 ret")
    index = load_index(args.index_path or DEFAULT_INDEX_PATHS, args.ma_window)

    specs = [("baseline", False, None, 1.0), ("csi1000_ma120", True, None, 1.0)]
    for threshold in [-0.03, -0.05, -0.08]:
        for exposure in [0.0, 0.5]:
            specs.append((f"loss_{threshold:.0%}_exp_{exposure:.0%}", False, threshold, exposure))
            specs.append((f"ma120_and_loss_{threshold:.0%}_exp_{exposure:.0%}", True, threshold, exposure))

    all_rows = []
    yearly_rows = []
    details = {}
    for name, use_index, threshold, loss_exposure in specs:
        d = apply_gate(perf, index, use_index, threshold, loss_exposure)
        m = eval_ret(d["gated_ret"].reset_index(drop=True))
        all_rows.append(
            {
                "rule": name,
                "use_csi1000_ma120": use_index,
                "loss_threshold": threshold,
                "loss_exposure": loss_exposure,
                "periods": m["periods"],
                "total_return": m["total"],
                "ann_return": m["ann"],
                "max_drawdown": m["mdd"],
                "win_rate": m["wr"],
                "avg_exposure": float(d["exposure"].mean()),
                "stopped_periods": int((d["exposure"] == 0).sum()),
                "reduced_periods": int((d["exposure"] < 1).sum()),
            }
        )
        y = yearly(d)
        y["rule"] = name
        yearly_rows.append(y)
        details[name] = d

    # 专门测试：停实盘后继续运行同一组合的虚拟账本，出现单期强势再恢复。
    shadow_name = "shadow_stop_-5%_resume_+5%"
    shadow = apply_shadow_recovery(perf, stop_threshold=-0.05, resume_threshold=0.05)
    shadow_m = eval_ret(shadow["gated_ret"].reset_index(drop=True))
    all_rows.append(
        {
            "rule": shadow_name,
            "use_csi1000_ma120": False,
            "loss_threshold": -0.05,
            "loss_exposure": 0.0,
            "periods": shadow_m["periods"],
            "total_return": shadow_m["total"],
            "ann_return": shadow_m["ann"],
            "max_drawdown": shadow_m["mdd"],
            "win_rate": shadow_m["wr"],
            "avg_exposure": float(shadow["exposure"].mean()),
            "stopped_periods": int((shadow["exposure"] == 0).sum()),
            "reduced_periods": int((shadow["exposure"] < 1).sum()),
        }
    )
    shadow_yearly = yearly(shadow)
    shadow_yearly["rule"] = shadow_name
    yearly_rows.append(shadow_yearly)
    details[shadow_name] = shadow

    summary = pd.DataFrame(all_rows)
    base = summary.loc[summary["rule"] == "baseline"].iloc[0]
    summary["delta_ann"] = summary["ann_return"] - base["ann_return"]
    summary["mdd_improvement"] = abs(base["max_drawdown"]) - abs(summary["max_drawdown"])
    summary["score"] = summary["delta_ann"] * 100.0 + summary["mdd_improvement"] * 80.0
    summary = summary.sort_values(["score", "ann_return"], ascending=False).reset_index(drop=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out_dir) / f"cb_trade_gate_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / "gate_summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(yearly_rows, ignore_index=True).to_csv(out / "gate_yearly.csv", index=False, encoding="utf-8-sig")
    for name, d in details.items():
        d.to_csv(out / f"periods_{name}.csv", index=False, encoding="utf-8-sig")

    print(f"交易开关研究完成 -> {out}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
