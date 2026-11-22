#!/usr/bin/env python3
"""Six-group comparison on QQQ/TQQQ with TQQQ annual fee.

Groups:
1) QQQ_DCA: monthly DCA into QQQ
2) QQQ_LUMPSUM: one-time buy QQQ at start
3) CORE60_SAT40_TIMING_DCA: QQQ 60% DCA always + TQQQ 40% DCA with QQQ SMA200 timing
4) CORE60_SAT40_TIMING_LUMPSUM: one-time 60/40 buy at start, with TQQQ timing by QQQ SMA200
5) TQQQ_DCA: monthly DCA into fee-adjusted TQQQ
6) TQQQ_LUMPSUM: one-time buy fee-adjusted TQQQ at start

TQQQ annual fee (default 0.82%) is applied as daily decay on TQQQ close:
adj_tqqq_close_t = tqqq_close_t * (1 - fee_annual/252)^day_index
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PerfRow:
    group: str
    start_date: str
    end_date: str
    months: int
    total_invested: float
    final_value: float
    total_return: float
    cagr: float
    max_drawdown: float
    max_value: float


def _load(path: str, col_name: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date_dt"] = pd.to_datetime(df["Unnamed: 0"], errors="coerce")
    df = df.dropna(subset=["date_dt", "close"]).sort_values("date_dt").reset_index(drop=True)
    out = df[["date_dt", "close"]].copy()
    out.rename(columns={"close": col_name}, inplace=True)
    return out


def _build_base(qqq_path: str, tqqq_path: str, tqqq_fee_annual: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = _load(qqq_path, "qqq")
    t = _load(tqqq_path, "tqqq")
    d = q.merge(t, on="date_dt", how="inner").sort_values("date_dt").reset_index(drop=True)
    d["sma200"] = d["qqq"].rolling(200, min_periods=200).mean()
    # fee-adjusted tqqq price
    daily_factor = 1.0 - tqqq_fee_annual / 252.0
    d["day_idx"] = np.arange(len(d))
    d["tqqq_adj"] = d["tqqq"] * np.power(daily_factor, d["day_idx"])
    d["month"] = d["date_dt"].dt.to_period("M").astype(str)
    m = d.groupby("month", as_index=False).tail(1).copy().reset_index(drop=True)
    return d, m


def _perf_from_monthly(monthly: pd.DataFrame, group: str, invested: float) -> PerfRow:
    v = monthly["value"].astype(float)
    eq_peak = v.cummax()
    dd = v / eq_peak - 1.0
    start_date = monthly["date"].iloc[0].date().isoformat()
    end_date = monthly["date"].iloc[-1].date().isoformat()
    months = len(monthly)
    final_value = float(v.iloc[-1])
    total_return = final_value / invested - 1.0 if invested > 0 else np.nan
    years = months / 12.0
    cagr = (final_value / invested) ** (1.0 / years) - 1.0 if invested > 0 and years > 0 else np.nan
    return PerfRow(
        group=group,
        start_date=start_date,
        end_date=end_date,
        months=months,
        total_invested=float(invested),
        final_value=final_value,
        total_return=float(total_return),
        cagr=float(cagr),
        max_drawdown=float(dd.min()),
        max_value=float(v.max()),
    )


def group1_qqq_dca(m: pd.DataFrame, monthly_invest: float) -> tuple[pd.DataFrame, PerfRow]:
    shares = 0.0
    invested = 0.0
    rows = []
    for _, r in m.iterrows():
        px = float(r["qqq"])
        shares += monthly_invest / px
        invested += monthly_invest
        rows.append({"date": r["date_dt"], "month": r["month"], "value": shares * px})
    monthly = pd.DataFrame(rows)
    return monthly, _perf_from_monthly(monthly, "QQQ_DCA", invested)


def group2_core_sat_timing(
    m: pd.DataFrame,
    monthly_invest: float,
    core_weight: float,
    sat_weight: float,
    buy_mult: float,
    sell_mult: float,
) -> tuple[pd.DataFrame, PerfRow]:
    qqq_shares = 0.0
    tqqq_shares = 0.0
    sat_cash = 0.0
    signal_on = False
    invested = 0.0
    rows = []
    for _, r in m.iterrows():
        q = float(r["qqq"])
        t = float(r["tqqq_adj"])
        sma = float(r["sma200"]) if pd.notna(r["sma200"]) else np.nan
        if pd.notna(sma):
            if (not signal_on) and (q > sma * buy_mult):
                signal_on = True
            elif signal_on and (q < sma * sell_mult):
                sat_cash += tqqq_shares * t
                tqqq_shares = 0.0
                signal_on = False

        core_cash = monthly_invest * core_weight
        sat_new_cash = monthly_invest * sat_weight
        invested += monthly_invest
        qqq_shares += core_cash / q
        if signal_on:
            sat_total = sat_cash + sat_new_cash
            if sat_total > 0:
                tqqq_shares += sat_total / t
                sat_cash = 0.0
        else:
            sat_cash += sat_new_cash

        val = qqq_shares * q + tqqq_shares * t + sat_cash
        rows.append({"date": r["date_dt"], "month": r["month"], "value": val})
    monthly = pd.DataFrame(rows)
    return monthly, _perf_from_monthly(monthly, "CORE60_SAT40_TIMING_DCA", invested)


def group3_qqq_lumpsum(m: pd.DataFrame, total_capital: float) -> tuple[pd.DataFrame, PerfRow]:
    first = m.iloc[0]
    q0 = float(first["qqq"])
    q_shares = total_capital / q0
    rows = []
    for _, r in m.iterrows():
        q = float(r["qqq"])
        rows.append({"date": r["date_dt"], "month": r["month"], "value": q_shares * q})
    monthly = pd.DataFrame(rows)
    return monthly, _perf_from_monthly(monthly, "QQQ_LUMPSUM", total_capital)


def group4_lumpsum_60_40_timing(
    m: pd.DataFrame, total_capital: float, buy_mult: float, sell_mult: float
) -> tuple[pd.DataFrame, PerfRow]:
    first = m.iloc[0]
    q0 = float(first["qqq"])
    t0 = float(first["tqqq_adj"])
    q_shares = (total_capital * 0.6) / q0
    t_shares = (total_capital * 0.4) / t0
    sat_cash = 0.0
    signal_on = True
    rows = []
    for i, r in m.iterrows():
        q = float(r["qqq"])
        t = float(r["tqqq_adj"])
        sma = float(r["sma200"]) if pd.notna(r["sma200"]) else np.nan
        if i > 0 and pd.notna(sma):
            if signal_on and q < sma * sell_mult:
                sat_cash += t_shares * t
                t_shares = 0.0
                signal_on = False
            elif (not signal_on) and q > sma * buy_mult:
                if sat_cash > 0:
                    t_shares += sat_cash / t
                    sat_cash = 0.0
                signal_on = True
        rows.append({"date": r["date_dt"], "month": r["month"], "value": q_shares * q + t_shares * t + sat_cash})
    monthly = pd.DataFrame(rows)
    return monthly, _perf_from_monthly(monthly, "CORE60_SAT40_TIMING_LUMPSUM", total_capital)


def group5_tqqq_dca(m: pd.DataFrame, monthly_invest: float) -> tuple[pd.DataFrame, PerfRow]:
    shares = 0.0
    invested = 0.0
    rows = []
    for _, r in m.iterrows():
        t = float(r["tqqq_adj"])
        shares += monthly_invest / t
        invested += monthly_invest
        rows.append({"date": r["date_dt"], "month": r["month"], "value": shares * t})
    monthly = pd.DataFrame(rows)
    return monthly, _perf_from_monthly(monthly, "TQQQ_DCA", invested)


def group6_tqqq_lumpsum(m: pd.DataFrame, total_capital: float) -> tuple[pd.DataFrame, PerfRow]:
    first = m.iloc[0]
    t0 = float(first["tqqq_adj"])
    shares = total_capital / t0
    rows = []
    for _, r in m.iterrows():
        t = float(r["tqqq_adj"])
        rows.append({"date": r["date_dt"], "month": r["month"], "value": shares * t})
    monthly = pd.DataFrame(rows)
    return monthly, _perf_from_monthly(monthly, "TQQQ_LUMPSUM", total_capital)


def main() -> None:
    p = argparse.ArgumentParser(description="QQQ/TQQQ four-group comparison")
    p.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    p.add_argument("--tqqq-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    p.add_argument("--monthly-invest", type=float, default=1000.0)
    p.add_argument("--buy-mult", type=float, default=1.04)
    p.add_argument("--sell-mult", type=float, default=0.97)
    p.add_argument("--tqqq-fee-annual", type=float, default=0.0082)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = p.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    _, m = _build_base(args.qqq_path, args.tqqq_path, args.tqqq_fee_annual)

    g1_m, g1 = group1_qqq_dca(m, args.monthly_invest)
    g2_m, g2 = group3_qqq_lumpsum(m, total_capital=args.monthly_invest * len(m))
    g3_m, g3 = group2_core_sat_timing(
        m,
        args.monthly_invest,
        core_weight=0.6,
        sat_weight=0.4,
        buy_mult=args.buy_mult,
        sell_mult=args.sell_mult,
    )
    total_capital = args.monthly_invest * len(m)
    g4_m, g4 = group4_lumpsum_60_40_timing(
        m, total_capital=total_capital, buy_mult=args.buy_mult, sell_mult=args.sell_mult
    )
    g5_m, g5 = group5_tqqq_dca(m, args.monthly_invest)
    g6_m, g6 = group6_tqqq_lumpsum(m, total_capital=total_capital)

    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"qqq_tqqq_four_group_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    g1_m.to_csv(os.path.join(out_dir, "group1_monthly.csv"), index=False, encoding="utf-8-sig")
    g2_m.to_csv(os.path.join(out_dir, "group2_monthly.csv"), index=False, encoding="utf-8-sig")
    g3_m.to_csv(os.path.join(out_dir, "group3_monthly.csv"), index=False, encoding="utf-8-sig")
    g4_m.to_csv(os.path.join(out_dir, "group4_monthly.csv"), index=False, encoding="utf-8-sig")
    g5_m.to_csv(os.path.join(out_dir, "group5_monthly.csv"), index=False, encoding="utf-8-sig")
    g6_m.to_csv(os.path.join(out_dir, "group6_monthly.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame([g1.__dict__, g2.__dict__, g3.__dict__, g4.__dict__, g5.__dict__, g6.__dict__])
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
