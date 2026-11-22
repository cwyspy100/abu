"""可转债组合因子月度轮动回测（含成本/流动性/风险约束）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_factor_decile_research import build_panel


def _max_drawdown(equity: pd.Series) -> float:
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    return float(dd.min()) if len(dd) else np.nan


def build_trade_path_cache(panel: pd.DataFrame) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Dict[pd.Timestamp, int]]]:
    """为持有期路径模拟建立缓存。"""
    cols = ["trade_date", "open", "high", "low", "close"]
    paths: Dict[str, pd.DataFrame] = {}
    pos_maps: Dict[str, Dict[pd.Timestamp, int]] = {}
    for code, grp in panel.dropna(subset=["ts_code", "trade_date"]).groupby("ts_code", sort=False):
        g = grp[cols].copy().sort_values("trade_date").reset_index(drop=True)
        paths[str(code)] = g
        pos_maps[str(code)] = {pd.Timestamp(dt): i for i, dt in enumerate(g["trade_date"])}
    return paths, pos_maps


def simulate_position_return(
    paths: Dict[str, pd.DataFrame],
    pos_maps: Dict[str, Dict[pd.Timestamp, int]],
    ts_code: str,
    rebalance_date: pd.Timestamp,
    hold_days: int = 20,
    stop_loss_pct: Optional[float] = None,
    take_half_price: Optional[float] = None,
    take_full_price: Optional[float] = None,
) -> dict:
    """按未来日线路径近似模拟卖出规则。

    规则说明：
    1. 持有起点为调仓日收盘价；
    2. 若日内高点触及 130，卖出 50%；
    3. 若日内高点触及 150，卖出剩余仓位；
    4. 若日内低点触及止损价，卖出剩余仓位；
    5. 若同日同时触及多个上行阈值，按 130 -> 150 顺序执行；
    6. 若直到持有期结束仍未触发，则按持有期最后一日收盘价结算剩余仓位。
    """
    code = str(ts_code)
    dt = pd.Timestamp(rebalance_date)
    grp = paths.get(code)
    pos = pos_maps.get(code, {}).get(dt)
    if grp is None or pos is None:
        return {
            "ret": np.nan,
            "exit_reason": "missing_path",
            "sold_half": False,
            "days_held": 0,
        }

    entry = float(grp.iloc[pos]["close"])
    if not np.isfinite(entry) or entry <= 0:
        return {
            "ret": np.nan,
            "exit_reason": "bad_entry",
            "sold_half": False,
            "days_held": 0,
        }

    future = grp.iloc[pos + 1: pos + 1 + int(hold_days)].copy()
    if future.empty:
        return {
            "ret": np.nan,
            "exit_reason": "no_future",
            "sold_half": False,
            "days_held": 0,
        }

    remaining = 1.0
    realized = 0.0
    sold_half = False
    exit_reason = "hold_to_end"
    stop_price = entry * (1.0 - float(stop_loss_pct)) if stop_loss_pct is not None else None

    for day_idx, row in enumerate(future.itertuples(index=False), start=1):
        high = float(row.high) if pd.notna(row.high) else np.nan
        low = float(row.low) if pd.notna(row.low) else np.nan

        if remaining > 0 and (not sold_half) and take_half_price is not None and pd.notna(high) and high >= float(take_half_price):
            realized += 0.5 * (float(take_half_price) / entry - 1.0)
            remaining -= 0.5
            sold_half = True

        if remaining > 0 and take_full_price is not None and pd.notna(high) and high >= float(take_full_price):
            realized += remaining * (float(take_full_price) / entry - 1.0)
            remaining = 0.0
            exit_reason = "take_full"
            return {
                "ret": realized,
                "exit_reason": exit_reason,
                "sold_half": sold_half,
                "days_held": day_idx,
            }

        if remaining > 0 and stop_price is not None and pd.notna(low) and low <= stop_price:
            realized += remaining * (stop_price / entry - 1.0)
            remaining = 0.0
            exit_reason = "stop_loss"
            return {
                "ret": realized,
                "exit_reason": exit_reason,
                "sold_half": sold_half,
                "days_held": day_idx,
            }

    last_close = float(future.iloc[-1]["close"])
    if remaining > 0 and np.isfinite(last_close):
        realized += remaining * (last_close / entry - 1.0)
    elif remaining > 0:
        return {
            "ret": np.nan,
            "exit_reason": "bad_last_close",
            "sold_half": sold_half,
            "days_held": len(future),
        }

    return {
        "ret": realized,
        "exit_reason": exit_reason,
        "sold_half": sold_half,
        "days_held": len(future),
    }


def calc_period_gross_return(
    panel: pd.DataFrame,
    picks: pd.DataFrame,
    rebalance_date: pd.Timestamp,
    hold_days: int = 20,
    stop_loss_pct: Optional[float] = None,
    take_half_price: Optional[float] = None,
    take_full_price: Optional[float] = None,
    path_cache: Optional[Tuple[Dict[str, pd.DataFrame], Dict[str, Dict[pd.Timestamp, int]]]] = None,
) -> tuple[float, pd.DataFrame]:
    """计算单期组合收益；若配置卖出规则，则按未来路径近似收益。"""
    if picks.empty:
        return np.nan, pd.DataFrame()

    rules_enabled = any(v is not None for v in [stop_loss_pct, take_half_price, take_full_price])
    if not rules_enabled:
        tmp = picks[["ts_code", "fwd_ret_20d"]].copy()
        tmp["sim_ret_20d"] = tmp["fwd_ret_20d"]
        tmp["exit_reason"] = "hold_to_end"
        tmp["sold_half"] = False
        tmp["days_held"] = hold_days
        return float(tmp["sim_ret_20d"].mean()), tmp

    if path_cache is None:
        path_cache = build_trade_path_cache(panel)
    paths, pos_maps = path_cache

    rows = []
    for r in picks.itertuples(index=False):
        sim = simulate_position_return(
            paths=paths,
            pos_maps=pos_maps,
            ts_code=str(r.ts_code),
            rebalance_date=pd.Timestamp(rebalance_date),
            hold_days=hold_days,
            stop_loss_pct=stop_loss_pct,
            take_half_price=take_half_price,
            take_full_price=take_full_price,
        )
        rows.append(
            {
                "ts_code": str(r.ts_code),
                "fwd_ret_20d": getattr(r, "fwd_ret_20d", np.nan),
                "sim_ret_20d": sim["ret"],
                "exit_reason": sim["exit_reason"],
                "sold_half": sim["sold_half"],
                "days_held": sim["days_held"],
            }
        )

    detail = pd.DataFrame(rows)
    gross = float(detail["sim_ret_20d"].dropna().mean()) if detail["sim_ret_20d"].notna().any() else np.nan
    return gross, detail


def run_backtest(
    panel: pd.DataFrame,
    score_col: str,
    top_n: int = 20,
    min_amount_wan: float = 3000.0,
    max_price_for_call_risk: float = 140.0,
    roundtrip_cost_bps: float = 40.0,
    hold_days: int = 20,
    stop_loss_pct: Optional[float] = None,
    take_half_price: Optional[float] = None,
    take_full_price: Optional[float] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """使用月末调仓，持有20交易日（用 fwd_ret_20d 近似）。"""
    df = panel.copy()
    df = df.dropna(subset=[score_col, "fwd_ret_20d", "trade_date"]).copy()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 交易约束：流动性过滤 + 强赎风险代理过滤
    if "amount" in df.columns:
        df = df[df["amount"] >= float(min_amount_wan)].copy()
    if "close" in df.columns:
        df = df[df["close"] <= float(max_price_for_call_risk)].copy()

    df["month"] = df["trade_date"].dt.to_period("M")
    rebal_dates = df.groupby("month")["trade_date"].max().sort_values().tolist()
    path_cache = build_trade_path_cache(df)

    rows = []
    hold_rows = []
    prev_hold: set[str] = set()
    for d in rebal_dates:
        cross = df[df["trade_date"] == d].copy()
        if len(cross) < top_n:
            continue
        picks = cross.sort_values(score_col, ascending=False).head(top_n)
        gross_ret, pick_detail = calc_period_gross_return(
            panel=df,
            picks=picks,
            rebalance_date=d,
            hold_days=hold_days,
            stop_loss_pct=stop_loss_pct,
            take_half_price=take_half_price,
            take_full_price=take_full_price,
            path_cache=path_cache,
        )
        if not np.isfinite(gross_ret):
            continue
        cur_hold = set(picks["ts_code"].astype(str).tolist())
        if not prev_hold:
            turnover = 1.0
        else:
            overlap = len(prev_hold & cur_hold)
            turnover = 1.0 - overlap / float(top_n)
        # roundtrip_cost_bps 为“满换手”成本，按换手率线性缩放
        cost = turnover * (roundtrip_cost_bps / 10000.0)
        period_ret = gross_ret - cost

        rows.append({
            "rebalance_date": d,
            "n": len(picks),
            "gross_ret_20d": gross_ret,
            "turnover": turnover,
            "cost": cost,
            "period_ret_20d": period_ret,
            "avg_score": picks[score_col].mean(),
        })
        tmp = picks[["ts_code", score_col, "fwd_ret_20d"]].copy()
        tmp = tmp.merge(pick_detail, on=["ts_code", "fwd_ret_20d"], how="left")
        tmp["rebalance_date"] = d
        hold_rows.append(tmp)
        prev_hold = cur_hold

    perf = pd.DataFrame(rows)
    holds = pd.concat(hold_rows, ignore_index=True) if hold_rows else pd.DataFrame()
    if perf.empty:
        return perf, holds

    perf = perf.sort_values("rebalance_date").reset_index(drop=True)
    perf["equity"] = (1.0 + perf["period_ret_20d"]).cumprod()
    return perf, holds


def summarize(perf: pd.DataFrame) -> dict:
    if perf.empty:
        return {
            "periods": 0,
            "ann_return": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
            "avg_period_ret": np.nan,
            "avg_turnover": np.nan,
            "avg_cost": np.nan,
        }

    total = float(perf["equity"].iloc[-1] - 1.0)
    periods = len(perf)
    per_year = 252.0 / 20.0
    ann = float((1.0 + total) ** (per_year / periods) - 1.0) if periods > 0 else np.nan
    mdd = _max_drawdown(perf["equity"])
    win_rate = float((perf["period_ret_20d"] > 0).mean())
    avg_ret = float(perf["period_ret_20d"].mean())
    avg_turnover = float(perf["turnover"].mean()) if "turnover" in perf.columns else np.nan
    avg_cost = float(perf["cost"].mean()) if "cost" in perf.columns else np.nan

    return {
        "periods": periods,
        "ann_return": ann,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "avg_period_ret": avg_ret,
        "avg_turnover": avg_turnover,
        "avg_cost": avg_cost,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="可转债组合因子月度轮动原型回测")
    parser.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    parser.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    parser.add_argument("--out-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--min-amount-wan", type=float, default=3000.0, help="最低成交额（万元）过滤")
    parser.add_argument("--max-price-for-call-risk", type=float, default=140.0, help="价格上限（强赎风险代理过滤）")
    parser.add_argument("--roundtrip-cost-bps", type=float, default=40.0, help="满换手双边成本（bps）")
    parser.add_argument("--hold-days", type=int, default=20, help="持有天数")
    parser.add_argument("--stop-loss-pct", type=float, default=None, help="止损比例，如 0.08 表示下跌 8% 卖出")
    parser.add_argument("--take-half-price", type=float, default=None, help="达到该价格卖出 50%")
    parser.add_argument("--take-full-price", type=float, default=None, help="达到该价格卖出剩余仓位")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_monthly_backtest_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_panel(args.cb_daily, args.cb_basic)
    panel = build_combo_factors(panel)

    score_cols = [
        "combo_dl_trend",
        "combo_dl_trend_call",
        "combo_lp_trend",
    ]

    summary_rows = []
    for col in score_cols:
        perf, holds = run_backtest(
            panel,
            col,
            top_n=args.top_n,
            min_amount_wan=args.min_amount_wan,
            max_price_for_call_risk=args.max_price_for_call_risk,
            roundtrip_cost_bps=args.roundtrip_cost_bps,
            hold_days=args.hold_days,
            stop_loss_pct=args.stop_loss_pct,
            take_half_price=args.take_half_price,
            take_full_price=args.take_full_price,
        )
        perf_path = os.path.join(out_dir, f"perf_{col}.csv")
        hold_path = os.path.join(out_dir, f"holds_{col}.csv")
        perf.to_csv(perf_path, index=False, encoding="utf-8-sig")
        holds.to_csv(hold_path, index=False, encoding="utf-8-sig")

        stat = summarize(perf)
        stat["strategy"] = col
        summary_rows.append(stat)

    summary = pd.DataFrame(summary_rows)
    summary = summary[
        [
            "strategy",
            "periods",
            "ann_return",
            "max_drawdown",
            "win_rate",
            "avg_period_ret",
            "avg_turnover",
            "avg_cost",
        ]
    ]
    summary_path = os.path.join(out_dir, "monthly_backtest_summary.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print(f"月度轮动回测完成 -> {out_dir}")
    print(f"摘要 -> {summary_path}")


if __name__ == "__main__":
    main()
