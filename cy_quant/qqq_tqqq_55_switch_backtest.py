#!/usr/bin/env python3
"""5-5 switch strategy on csv_his:

- Start: 100% QQQ (lumpsum)
- QQQ up-cross MA120: sell half QQQ -> buy TQQQ
- QQQ down-cross MA120: sell all TQQQ -> buy QQQ

Compare with:
1) QQQ lumpsum buy & hold
2) QQQ monthly DCA
3) TQQQ timing by QQQ MA120 (above hold TQQQ, below hold cash)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Perf:
    group: str
    start_date: str
    end_date: str
    total_invested: float
    final_value: float
    total_return: float
    cagr: float
    max_drawdown: float
    max_value: float


def load_prices(qqq_path: str, tqqq_path: str) -> pd.DataFrame:
    q = pd.read_csv(qqq_path)
    t = pd.read_csv(tqqq_path)
    q["date_dt"] = pd.to_datetime(q["Unnamed: 0"], errors="coerce")
    t["date_dt"] = pd.to_datetime(t["Unnamed: 0"], errors="coerce")
    q = q.dropna(subset=["date_dt", "close"])[["date_dt", "close"]].rename(columns={"close": "qqq"})
    t = t.dropna(subset=["date_dt", "close"])[["date_dt", "close"]].rename(columns={"close": "tqqq"})
    d = q.merge(t, on="date_dt", how="inner").sort_values("date_dt").reset_index(drop=True)
    d["ma120"] = d["qqq"].rolling(120, min_periods=120).mean()
    d["month"] = d["date_dt"].dt.to_period("M").astype(str)
    return d


def perf_from_equity(equity: pd.Series, invested: float, group: str, dates: pd.Series) -> Perf:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    final_value = float(equity.iloc[-1])
    total_ret = final_value / invested - 1.0 if invested > 0 else np.nan
    cagr = (final_value / invested) ** (1.0 / years) - 1.0 if invested > 0 and years > 0 else np.nan
    return Perf(
        group=group,
        start_date=dates.iloc[0].date().isoformat(),
        end_date=dates.iloc[-1].date().isoformat(),
        total_invested=float(invested),
        final_value=final_value,
        total_return=float(total_ret),
        cagr=float(cagr),
        max_drawdown=float(dd.min()),
        max_value=float(equity.max()),
    )


def run_switch_55(d: pd.DataFrame, initial_capital: float) -> tuple[pd.DataFrame, Perf]:
    q_shares = initial_capital / float(d["qqq"].iloc[0])
    t_shares = 0.0
    rows = []
    for i, r in d.iterrows():
        q = float(r["qqq"])
        t = float(r["tqqq"])
        ma = float(r["ma120"]) if pd.notna(r["ma120"]) else np.nan
        if i > 0 and pd.notna(ma):
            prev_q = float(d.loc[i - 1, "qqq"])
            prev_ma = float(d.loc[i - 1, "ma120"]) if pd.notna(d.loc[i - 1, "ma120"]) else np.nan
            up_cross = pd.notna(prev_ma) and (prev_q <= prev_ma) and (q > ma)
            down_cross = pd.notna(prev_ma) and (prev_q >= prev_ma) and (q < ma)
            if up_cross:
                # sell half QQQ, buy TQQQ (only if satellite empty or partially empty; rebalance to 50/50)
                total_val = q_shares * q + t_shares * t
                target_sat = total_val * 0.5
                cur_sat = t_shares * t
                need_buy = max(0.0, target_sat - cur_sat)
                if need_buy > 0:
                    q_sell_shares = min(q_shares, need_buy / q)
                    q_shares -= q_sell_shares
                    t_shares += (q_sell_shares * q) / t
            elif down_cross:
                # clear TQQQ to QQQ
                if t_shares > 0:
                    cash = t_shares * t
                    t_shares = 0.0
                    q_shares += cash / q

        val = q_shares * q + t_shares * t
        rows.append(
            {
                "date": r["date_dt"],
                "qqq": q,
                "tqqq": t,
                "ma120": ma,
                "qqq_shares": q_shares,
                "tqqq_shares": t_shares,
                "value": val,
            }
        )
    out = pd.DataFrame(rows)
    perf = perf_from_equity(out["value"], initial_capital, "SWITCH_55_QQQ_TQQQ", out["date"])
    return out, perf


def run_qqq_lumpsum(d: pd.DataFrame, initial_capital: float) -> tuple[pd.DataFrame, Perf]:
    q_shares = initial_capital / float(d["qqq"].iloc[0])
    out = pd.DataFrame({"date": d["date_dt"], "value": q_shares * d["qqq"]})
    perf = perf_from_equity(out["value"], initial_capital, "QQQ_LUMPSUM", out["date"])
    return out, perf


def run_qqq_dca(d: pd.DataFrame, monthly_invest: float) -> tuple[pd.DataFrame, Perf]:
    month_end = d.groupby("month", as_index=False).tail(1).copy()
    month_end["is_buy_day"] = True
    tmp = d.merge(month_end[["date_dt", "is_buy_day"]], on="date_dt", how="left")
    tmp["is_buy_day"] = tmp["is_buy_day"].fillna(False)

    shares = 0.0
    invested = 0.0
    rows = []
    for _, r in tmp.iterrows():
        q = float(r["qqq"])
        if bool(r["is_buy_day"]):
            shares += monthly_invest / q
            invested += monthly_invest
        rows.append({"date": r["date_dt"], "value": shares * q})
    out = pd.DataFrame(rows)
    perf = perf_from_equity(out["value"], invested, "QQQ_DCA", out["date"])
    return out, perf


def run_tqqq_ma120_timing(d: pd.DataFrame, initial_capital: float) -> tuple[pd.DataFrame, Perf]:
    cash = initial_capital
    t_shares = 0.0
    rows = []
    for i, r in d.iterrows():
        q = float(r["qqq"])
        t = float(r["tqqq"])
        ma = float(r["ma120"]) if pd.notna(r["ma120"]) else np.nan
        if i > 0 and pd.notna(ma):
            prev_q = float(d.loc[i - 1, "qqq"])
            prev_ma = float(d.loc[i - 1, "ma120"]) if pd.notna(d.loc[i - 1, "ma120"]) else np.nan
            up_cross = pd.notna(prev_ma) and (prev_q <= prev_ma) and (q > ma)
            down_cross = pd.notna(prev_ma) and (prev_q >= prev_ma) and (q < ma)
            if up_cross and cash > 0:
                t_shares += cash / t
                cash = 0.0
            elif down_cross and t_shares > 0:
                cash += t_shares * t
                t_shares = 0.0
        val = cash + t_shares * t
        rows.append({"date": r["date_dt"], "value": val, "qqq": q, "tqqq": t, "ma120": ma, "cash": cash, "t_shares": t_shares})
    out = pd.DataFrame(rows)
    perf = perf_from_equity(out["value"], initial_capital, "TQQQ_MA120_TIMING", out["date"])
    return out, perf


def main() -> None:
    p = argparse.ArgumentParser(description="5-5 switch backtest on QQQ/TQQQ")
    p.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    p.add_argument("--tqqq-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    p.add_argument("--initial-capital", type=float, default=73000.0)
    p.add_argument("--monthly-invest", type=float, default=1000.0)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = p.parse_args()

    d = load_prices(args.qqq_path, args.tqqq_path)
    g1_df, g1 = run_switch_55(d, args.initial_capital)
    g2_df, g2 = run_qqq_lumpsum(d, args.initial_capital)
    g3_df, g3 = run_qqq_dca(d, args.monthly_invest)
    g4_df, g4 = run_tqqq_ma120_timing(d, args.initial_capital)

    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"qqq_tqqq_switch55_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    g1_df.to_csv(os.path.join(out_dir, "group1_switch55_daily.csv"), index=False, encoding="utf-8-sig")
    g2_df.to_csv(os.path.join(out_dir, "group2_qqq_lumpsum_daily.csv"), index=False, encoding="utf-8-sig")
    g3_df.to_csv(os.path.join(out_dir, "group3_qqq_dca_daily.csv"), index=False, encoding="utf-8-sig")
    g4_df.to_csv(os.path.join(out_dir, "group4_tqqq_ma120_timing_daily.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame([g1.__dict__, g2.__dict__, g3.__dict__, g4.__dict__])
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
