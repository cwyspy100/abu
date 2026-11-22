#!/usr/bin/env python3
"""Compare obs=10 vs obs=30 on us/hk from ~/abu/data/csv.

Outputs:
1) event panels
2) pick details
3) monthly summaries
4) overall summary
5) latest-month candidate list
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def load_market_files(csv_dir: str, prefix: str, max_files: int) -> List[str]:
    files = [f for f in glob.glob(os.path.join(csv_dir, f"{prefix}*")) if os.path.isfile(f)]
    files = [f for f in files if not os.path.basename(f).startswith(f"{prefix}.")]
    return sorted(files)[:max_files]


def parse_symbol(path: str, prefix: str) -> str:
    b = os.path.basename(path)
    s = b[len(prefix) :].split("_")[0]
    return f"{prefix}{s}"


def build_events(csv_dir: str, prefix: str, obs_days: int, max_files: int) -> pd.DataFrame:
    events: List[Dict] = []
    for fp in load_market_files(csv_dir, prefix, max_files):
        try:
            d = pd.read_csv(fp)
        except Exception:
            continue

        if "close" not in d.columns:
            continue

        dcol = "Unnamed: 0" if "Unnamed: 0" in d.columns else ("date" if "date" in d.columns else None)
        if dcol is None:
            continue

        d["dt"] = pd.to_datetime(d[dcol].astype(str), errors="coerce")
        d = d.dropna(subset=["dt", "close"]).sort_values("dt").reset_index(drop=True)
        if len(d) < (140 + obs_days + 120):
            continue

        d["ma120"] = d["close"].rolling(120, min_periods=120).mean()
        d["ma120_prev"] = d["ma120"].shift(1)
        d["close_prev"] = d["close"].shift(1)
        d["ma120_slope5"] = d["ma120"] - d["ma120"].shift(5)
        cross = (d["close"] > d["ma120"]) & (d["close_prev"] <= d["ma120_prev"]) & (d["ma120_slope5"] > 0)
        idx = np.where(cross.fillna(False).values)[0]
        if len(idx) == 0:
            continue

        sym = parse_symbol(fp, prefix)
        c = d["close"].values
        dates = d["dt"].values
        for i in idx:
            p0 = i
            ev = i + obs_days
            buy = ev + 1
            s60 = buy + 60
            s120 = buy + 120
            if s120 >= len(d):
                continue

            p0c = float(c[p0])
            evc = float(c[ev])
            buyc = float(c[buy])
            obs_slice = c[p0 + 1 : ev + 1]
            if len(obs_slice) == 0:
                continue

            close_above = int((obs_slice > p0c).sum())
            ret_obs = float(evc / p0c - 1.0)
            dd = float((obs_slice / p0c - 1.0).min())
            trend = close_above / float(obs_days)
            score = 60.0 * trend + 25.0 * max(ret_obs, 0.0) + 15.0 * (1.0 + dd)

            events.append(
                {
                    "market": prefix,
                    "symbol": sym,
                    "p0_date": pd.Timestamp(dates[p0]).date().isoformat(),
                    "eval_date": pd.Timestamp(dates[ev]).date().isoformat(),
                    "buy_date": pd.Timestamp(dates[buy]).date().isoformat(),
                    "sell_date_60d": pd.Timestamp(dates[s60]).date().isoformat(),
                    "sell_date_120d": pd.Timestamp(dates[s120]).date().isoformat(),
                    "close_above_p0_days": close_above,
                    "ret_obs": ret_obs,
                    "max_drawdown_from_p0": dd,
                    "total_score": score,
                    "ret_60d": float(c[s60] / buyc - 1.0),
                    "ret_120d": float(c[s120] / buyc - 1.0),
                }
            )

    out = pd.DataFrame(events)
    if not out.empty:
        out["eval_date"] = pd.to_datetime(out["eval_date"])
        out["month"] = out["eval_date"].dt.to_period("M").astype(str)
    return out


def select_and_eval(panel: pd.DataFrame, obs_days: int, rule_tag: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    if panel.empty:
        return pd.DataFrame(), pd.DataFrame(), {"months": 0}

    months = sorted(panel["month"].unique())
    train_m, test_m, step = 8, 3, 3
    min_close = max(1, int(np.ceil(obs_days * 0.6)))
    picks: List[pd.DataFrame] = []

    for s in range(0, max(0, len(months) - train_m - test_m + 1), step):
        trm = months[s : s + train_m]
        tem = months[s + train_m : s + train_m + test_m]
        tr = panel[panel["month"].isin(trm)].copy()
        te = panel[panel["month"].isin(tem)].copy()
        if tr.empty or te.empty:
            continue

        gate = max(min_close, float(tr["close_above_p0_days"].quantile(0.6)))
        q_score = float(tr["total_score"].quantile(0.6))
        cand = te[(te["close_above_p0_days"] >= gate) & (te["total_score"] >= q_score)].copy()
        for m, g in cand.groupby("month"):
            top = g.sort_values("total_score", ascending=False).head(30).copy()
            if top.empty:
                continue
            top["rule_tag"] = rule_tag
            top["obs_days"] = obs_days
            top["pick_month"] = m
            top["train_start"] = trm[0]
            top["train_end"] = trm[-1]
            top["test_start"] = tem[0]
            top["test_end"] = tem[-1]
            top["gate_close_days"] = gate
            top["gate_score"] = q_score
            picks.append(top)

    if not picks:
        return pd.DataFrame(), pd.DataFrame(), {"months": 0}

    p = pd.concat(picks, ignore_index=True)
    m = (
        p.groupby("pick_month", as_index=False)
        .agg(
            picks=("symbol", "count"),
            avg_ret_60d=("ret_60d", "mean"),
            avg_ret_120d=("ret_120d", "mean"),
            med_ret_120d=("ret_120d", "median"),
            win_rate_120d=("ret_120d", lambda s: float((s > 0).mean())),
        )
        .sort_values("pick_month")
    )
    r = m["avg_ret_120d"]
    eq = (1 + r).cumprod()
    n = len(r)
    perf = {
        "months": int(n),
        "total_return": float(eq.iloc[-1] - 1) if n else np.nan,
        "cagr": float(eq.iloc[-1] ** (12.0 / n) - 1) if n and eq.iloc[-1] > 0 else np.nan,
        "annual_vol": float(r.std(ddof=0) * np.sqrt(12)) if n > 1 else 0.0,
        "max_drawdown": float((eq / eq.cummax() - 1).min()) if n else np.nan,
        "win_rate": float((r > 0).mean()) if n else np.nan,
        "avg_ret_120d_pick": float(p["ret_120d"].mean()),
        "pick_count": int(len(p)),
    }
    return p, m, perf


def run(csv_dir: str, output_dir: str, max_files: int, recent_months: int) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"datacsv_us_hk_obs10_30_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    summary = []
    latest_rows = []

    for market in ["us", "hk"]:
        for obs in [10, 30]:
            panel = build_events(csv_dir, market, obs, max_files=max_files)
            panel.to_csv(os.path.join(out_dir, f"{market}_obs{obs}_event_panel.csv"), index=False, encoding="utf-8-sig")

            picks, monthly, perf = select_and_eval(panel, obs, f"{market}_obs{obs}_rule")
            picks.to_csv(os.path.join(out_dir, f"{market}_obs{obs}_picks_detail.csv"), index=False, encoding="utf-8-sig")
            monthly.to_csv(
                os.path.join(out_dir, f"{market}_obs{obs}_monthly_summary.csv"), index=False, encoding="utf-8-sig"
            )

            if not picks.empty:
                latest_months = sorted(picks["pick_month"].unique())[-recent_months:]
                latest = picks[picks["pick_month"].isin(latest_months)].copy()
                latest.to_csv(
                    os.path.join(out_dir, f"{market}_obs{obs}_latest_{recent_months}m_candidates.csv"),
                    index=False,
                    encoding="utf-8-sig",
                )
                latest_rows.append(latest)

            row = {
                "market": market,
                "obs_days": obs,
                "events": int(len(panel)),
                "event_start": panel["eval_date"].min().date().isoformat() if not panel.empty else None,
                "event_end": panel["eval_date"].max().date().isoformat() if not panel.empty else None,
            }
            row.update(perf)
            summary.append(row)

    sumdf = pd.DataFrame(summary)
    sumdf.to_csv(os.path.join(out_dir, "us_hk_obs10_30_overall_summary.csv"), index=False, encoding="utf-8-sig")
    if latest_rows:
        pd.concat(latest_rows, ignore_index=True).to_csv(
            os.path.join(out_dir, f"all_markets_latest_{recent_months}m_candidates.csv"), index=False, encoding="utf-8-sig"
        )
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="US/HK obs=10/30 comparison on abu/data/csv")
    p.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--max-files", type=int, default=2500)
    p.add_argument("--recent-months", type=int, default=1)
    args = p.parse_args()
    out = run(args.csv_dir, args.output_dir, args.max_files, args.recent_months)
    print(out)


if __name__ == "__main__":
    main()
