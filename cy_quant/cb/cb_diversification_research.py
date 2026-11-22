"""可转债横截面分散约束研究。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_combo_monthly_backtest import build_trade_path_cache, calc_period_gross_return
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_real_call_filter_backtest import build_real_call_intervals, apply_real_call_filter


def summarize_returns(rets: List[float]) -> dict:
    if not rets:
        return {"periods": 0, "ann_return": np.nan, "total_return": np.nan, "max_drawdown": np.nan, "win_rate": np.nan}
    s = pd.Series(rets)
    eq = (1.0 + s).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(s)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((s > 0).mean())
    return {"periods": len(s), "ann_return": ann, "total_return": total, "max_drawdown": mdd, "win_rate": wr}


def pick_top(cross: pd.DataFrame, top_n: int) -> pd.DataFrame:
    return cross.head(top_n)


def pick_one_per_stk(cross: pd.DataFrame, top_n: int) -> pd.DataFrame:
    c = cross.drop_duplicates(subset=["stk_code"], keep="first")
    return c.head(top_n)


def pick_balanced_premium(cross: pd.DataFrame, top_n: int) -> pd.DataFrame:
    c = cross.copy()
    if c["bond_over_rate"].notna().sum() < 10:
        return c.head(top_n)
    try:
        c["prem_bin"] = pd.qcut(c["bond_over_rate"].rank(method="first"), q=3, labels=[0, 1, 2])
    except Exception:
        return c.head(top_n)

    quota = int(np.ceil(top_n / 3.0))
    picks = []
    for b in [0, 1, 2]:
        sub = c[c["prem_bin"] == b].head(quota)
        picks.append(sub)
    out = pd.concat(picks, ignore_index=True).drop_duplicates(subset=["ts_code"], keep="first")
    out = out.sort_values("score", ascending=False).head(top_n)
    return out


def pick_combo(cross: pd.DataFrame, top_n: int) -> pd.DataFrame:
    c = cross.drop_duplicates(subset=["stk_code"], keep="first").copy()
    return pick_balanced_premium(c, top_n)


def run(
    panel: pd.DataFrame,
    mode: str,
    top_n: int,
    min_amount_wan: float,
    cost_bps: float,
    hold_days: int = 20,
    stop_loss_pct: float | None = None,
    take_half_price: float | None = None,
    take_full_price: float | None = None,
) -> dict:
    d = panel.dropna(subset=["score", "fwd_ret_20d", "trade_date"]).copy()
    d = d[d["amount"] >= min_amount_wan].copy()
    d["month"] = d["trade_date"].dt.to_period("M")
    rebal_dates = d.groupby("month")["trade_date"].max().sort_values().tolist()
    path_cache = build_trade_path_cache(d)

    prev = set()
    rets = []
    turns = []

    for dt in rebal_dates:
        cross = d[d["trade_date"] == dt].copy().sort_values("score", ascending=False)
        if len(cross) < top_n:
            continue

        if mode == "baseline":
            picks = pick_top(cross, top_n)
        elif mode == "one_per_stk":
            picks = pick_one_per_stk(cross, top_n)
        elif mode == "balanced_premium":
            picks = pick_balanced_premium(cross, top_n)
        elif mode == "combo":
            picks = pick_combo(cross, top_n)
        else:
            raise ValueError(mode)

        if len(picks) < top_n:
            # 兜底补齐
            missing = top_n - len(picks)
            rest = cross[~cross["ts_code"].isin(set(picks["ts_code"]))].head(missing)
            picks = pd.concat([picks, rest], ignore_index=True)

        gross, _ = calc_period_gross_return(
            panel=d,
            picks=picks,
            rebalance_date=pd.Timestamp(dt),
            hold_days=hold_days,
            stop_loss_pct=stop_loss_pct,
            take_half_price=take_half_price,
            take_full_price=take_full_price,
            path_cache=path_cache,
        )
        if not np.isfinite(gross):
            continue
        cur = set(picks["ts_code"].astype(str).tolist())
        if not prev:
            turn = 1.0
        else:
            turn = 1.0 - len(prev & cur) / float(top_n)
        cost = turn * (cost_bps / 10000.0)
        net = gross - cost
        rets.append(net)
        turns.append(turn)
        prev = cur

    s = summarize_returns(rets)
    s["avg_turnover"] = float(np.mean(turns)) if turns else np.nan
    s["mode"] = mode
    return s


def main() -> None:
    p = argparse.ArgumentParser(description="可转债分散约束研究")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument("--min-amount-wan", type=float, default=2000)
    p.add_argument("--cost-bps", type=float, default=40)
    p.add_argument("--hold-days", type=int, default=20)
    p.add_argument("--stop-loss-pct", type=float, default=None)
    p.add_argument("--take-half-price", type=float, default=None)
    p.add_argument("--take-full-price", type=float, default=None)
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_diversification_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    # 主策略 score 采用 combo_dl_trend
    panel["score"] = panel["combo_dl_trend"]

    # merge stk_code
    basic = pd.read_csv(args.cb_basic, dtype={"ts_code": str, "stk_code": str})
    basic = basic[["ts_code", "stk_code"]].drop_duplicates(subset=["ts_code"], keep="first")
    panel = panel.merge(basic, on="ts_code", how="left")
    panel["stk_code"] = panel["stk_code"].fillna(panel["ts_code"])

    panel = apply_real_call_filter(panel, build_real_call_intervals(args.cb_call))

    rows = []
    for mode in ["baseline", "one_per_stk", "balanced_premium", "combo"]:
        rows.append(
            run(
                panel,
                mode,
                args.top_n,
                args.min_amount_wan,
                args.cost_bps,
                hold_days=args.hold_days,
                stop_loss_pct=args.stop_loss_pct,
                take_half_price=args.take_half_price,
                take_full_price=args.take_full_price,
            )
        )

    out = pd.DataFrame(rows)
    out = out[["mode", "periods", "ann_return", "total_return", "max_drawdown", "win_rate", "avg_turnover"]]
    out.to_csv(os.path.join(out_dir, "diversification_summary.csv"), index=False, encoding="utf-8-sig")

    print(f"分散约束研究完成 -> {out_dir}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
