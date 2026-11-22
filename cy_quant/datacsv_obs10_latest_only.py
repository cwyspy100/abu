#!/usr/bin/env python3
"""Generate latest-month candidates using only MA120 cross + 10-day observation.

No future 120-day return requirement.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd


def load_files(csv_dir: str, prefix: str, max_files: int) -> List[str]:
    files = [f for f in glob.glob(os.path.join(csv_dir, f"{prefix}*")) if os.path.isfile(f)]
    files = [f for f in files if not os.path.basename(f).startswith(f"{prefix}.")]
    return sorted(files)[:max_files]


def parse_symbol(path: str, prefix: str) -> str:
    b = os.path.basename(path)
    code = b[len(prefix) :].split("_")[0]
    return f"{prefix}{code}"


def build_latest_candidates(
    csv_dir: str, obs_days: int, target_month: str, max_files: int
) -> pd.DataFrame:
    rows: List[Dict] = []
    markets = [("sh", "A"), ("sz", "A"), ("hk", "HK"), ("us", "US")]
    for prefix, market in markets:
        for fp in load_files(csv_dir, prefix, max_files):
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
            if len(d) < (140 + obs_days):
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
            dt = d["dt"].values
            for i in idx:
                ev = i + obs_days
                if ev >= len(d):
                    continue
                eval_date = pd.Timestamp(dt[ev])
                if eval_date.strftime("%Y-%m") != target_month:
                    continue

                p0c = float(c[i])
                evc = float(c[ev])
                obs_slice = c[i + 1 : ev + 1]
                if len(obs_slice) == 0:
                    continue

                close_above = int((obs_slice > p0c).sum())
                ret_obs = float(evc / p0c - 1.0)
                dd = float((obs_slice / p0c - 1.0).min())
                score = 60.0 * (close_above / obs_days) + 25.0 * max(ret_obs, 0.0) + 15.0 * (1.0 + dd)
                rows.append(
                    {
                        "market": market,
                        "symbol": sym,
                        "p0_date": pd.Timestamp(dt[i]).date().isoformat(),
                        "eval_date": eval_date.date().isoformat(),
                        "close_above_p0_days": close_above,
                        "ret_obs_10d": ret_obs,
                        "max_drawdown_from_p0": dd,
                        "score": score,
                        "close_eval": evc,
                        "ma120_eval": float(d.loc[ev, "ma120"]) if pd.notna(d.loc[ev, "ma120"]) else np.nan,
                        "ma120_slope5_eval": float(d.loc[ev, "ma120_slope5"])
                        if pd.notna(d.loc[ev, "ma120_slope5"])
                        else np.nan,
                    }
                )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["market", "score"], ascending=[True, False]).reset_index(drop=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Latest-month candidates with 10-day observation only.")
    p.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--obs-days", type=int, default=10)
    p.add_argument("--target-month", default=None, help="YYYY-MM, default current month")
    p.add_argument("--max-files", type=int, default=3000)
    args = p.parse_args()

    target_month = args.target_month or datetime.now().strftime("%Y-%m")
    out_dir = os.path.join(args.output_dir, f"latest_obs10_only_{target_month.replace('-', '')}")
    os.makedirs(out_dir, exist_ok=True)

    df = build_latest_candidates(args.csv_dir, args.obs_days, target_month, args.max_files)
    if df.empty:
        print(f"No candidates for {target_month}")
        return

    df.to_csv(os.path.join(out_dir, f"all_candidates_{target_month.replace('-', '_')}.csv"), index=False, encoding="utf-8-sig")
    latest_day = df["eval_date"].max()
    df[df["eval_date"] == latest_day].to_csv(
        os.path.join(out_dir, f"latest_day_candidates_{target_month.replace('-', '_')}.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    for m, g in df.groupby("market"):
        g.to_csv(
            os.path.join(out_dir, f"{m.lower()}_candidates_{target_month.replace('-', '_')}.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    print(out_dir)


if __name__ == "__main__":
    main()
