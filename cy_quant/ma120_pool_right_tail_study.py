#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Right-tail study for MA120 candidate pool.

This script intentionally avoids trading-rule tuning. It compares the future
return distribution of MA120 candidates with random stocks sampled on the same
entry dates.
"""

from __future__ import annotations

import argparse
import glob
import os
import warnings
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)


def _scan_csv_map(csv_dir: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in glob.glob(os.path.join(csv_dir, "*")):
        if os.path.isdir(p):
            continue
        stem = os.path.basename(p)
        if stem.endswith(".csv"):
            stem = stem[:-4]
        if "_" not in stem:
            continue
        code_part = stem.split("_", 1)[0]
        if len(code_part) < 3:
            continue
        prefix = code_part[:2].lower()
        num = code_part[2:]
        market = {"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}.get(prefix)
        if market is not None:
            out[f"{num}.{market}"] = p
    return out


def _symbol_to_ts_code(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "ts_code" in out.columns or "symbol" not in out.columns:
        return out
    s = out["symbol"].astype(str)
    prefix = s.str[:2].str.lower()
    num = s.str[2:]
    market = prefix.map({"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}).fillna("")
    out["ts_code"] = np.where(market != "", num + "." + market, np.nan)
    return out


def _load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=lambda c: c in {"date", "close"})
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"].astype(str), format="%Y%m%d", errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    return out


def _future_ret(
    k: pd.DataFrame,
    entry_date: pd.Timestamp,
    horizon: int,
    require_ma120: bool = False,
) -> Optional[Dict[str, object]]:
    idx = k.index[k["date"] >= entry_date]
    if len(idx) == 0:
        return None
    i0 = int(idx[0])
    i1 = i0 + horizon
    if i1 >= len(k):
        return None
    if require_ma120:
        ma120 = k.iloc[i0].get("ma120")
        if pd.isna(ma120) or float(k.iloc[i0]["close"]) <= float(ma120):
            return None
    buy = float(k.iloc[i0]["close"])
    sell = float(k.iloc[i1]["close"])
    if buy <= 0:
        return None
    return {
        "entry_date": pd.Timestamp(k.iloc[i0]["date"]),
        "exit_date": pd.Timestamp(k.iloc[i1]["date"]),
        "ret": sell / buy - 1.0,
    }


def _load_candidates(panel_csv: str, markets: str, min_close_above: int, min_ret_obs: float) -> pd.DataFrame:
    df = pd.read_csv(panel_csv)
    df = _symbol_to_ts_code(df)
    if markets:
        allow = {m.strip().upper() for m in markets.split(",") if m.strip()}
        df = df[df["ts_code"].astype(str).str.split(".").str[-1].isin(allow)].copy()
    # Exclude index-like A-share symbols such as 000001.SH in current generated panels.
    df = df[~df["ts_code"].astype(str).str.match(r"^000\\d{3}\\.SH$")].copy()
    if "ret_30d_from_p0" not in df.columns:
        df["ret_30d_from_p0"] = df["ret_obs_10d"] if "ret_obs_10d" in df.columns else df.get("ret_30d", np.nan)
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    df = df.dropna(subset=["ts_code", "eval_date", "buy_date", "total_score"]).copy()
    df = df[(df["close_above_p0_days"] >= min_close_above) & (df["ret_30d_from_p0"] > min_ret_obs)].copy()
    return df.sort_values(["buy_date", "total_score"], ascending=[True, False]).reset_index(drop=True)


def _winner_top_share(r: pd.Series, pct: float = 0.1) -> float:
    pos = r[r > 0].sort_values(ascending=False)
    total = float(pos.sum())
    if total <= 0 or pos.empty:
        return np.nan
    n = max(1, int(np.ceil(len(pos) * pct)))
    return float(pos.head(n).sum() / total)


def _summary(label: str, ret: pd.Series) -> Dict[str, object]:
    r = pd.to_numeric(ret, errors="coerce").dropna()
    if r.empty:
        return {"group": label, "n": 0}
    return {
        "group": label,
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win_rate": float((r > 0).mean()),
        "q10": float(r.quantile(0.10)),
        "q25": float(r.quantile(0.25)),
        "q75": float(r.quantile(0.75)),
        "q90": float(r.quantile(0.90)),
        "q95": float(r.quantile(0.95)),
        "max": float(r.max()),
        "tail_gt10": float((r >= 0.10).mean()),
        "tail_gt20": float((r >= 0.20).mean()),
        "tail_gt30": float((r >= 0.30).mean()),
        "loss_lt10": float((r <= -0.10).mean()),
        "winner_top10_share": _winner_top_share(r, 0.10),
    }


def _fold_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for g, sub in df.groupby(group_col):
        d = sub.sort_values("entry_date").copy()
        if len(d) < 10:
            continue
        d["fold"] = pd.qcut(np.arange(len(d)), q=3, labels=["fold1", "fold2", "fold3"])
        for fold, fdf in d.groupby("fold"):
            row = _summary(str(g), fdf["ret"])
            row["fold"] = str(fold)
            rows.append(row)
    return pd.DataFrame(rows)


def run(
    label: str,
    panel_csv: str,
    csv_dir: str,
    output_dir: str,
    markets: str,
    min_close_above: int,
    min_ret_obs: float,
    horizon: int,
    random_mult: int,
    seed: int,
    random_require_ma120: bool,
) -> str:
    rng = np.random.default_rng(seed)
    csv_map = _scan_csv_map(csv_dir)
    codes = sorted([c for c in csv_map if c.endswith(".SH") or c.endswith(".SZ")])
    stock_codes = [c for c in codes if not c.startswith("000") or not c.endswith(".SH")]
    candidates = _load_candidates(panel_csv, markets, min_close_above, min_ret_obs)
    cache: Dict[str, pd.DataFrame] = {}

    rows: List[Dict[str, object]] = []
    for _, row in candidates.iterrows():
        ts_code = str(row["ts_code"])
        path = csv_map.get(ts_code)
        if path is None:
            continue
        if path not in cache:
            cache[path] = _load_kline(path)
        fr = _future_ret(cache[path], pd.Timestamp(row["buy_date"]), horizon)
        if fr is None:
            continue
        rows.append(
            {
                "group": "candidate",
                "ts_code": ts_code,
                "entry_date": fr["entry_date"],
                "exit_date": fr["exit_date"],
                "ret": fr["ret"],
                "score": row.get("total_score", np.nan),
            }
        )

        sample_size = min(random_mult, len(stock_codes))
        seen = set()
        sampled_count = 0
        max_attempts = min(len(stock_codes), max(random_mult * 30, random_mult))
        for rc in rng.choice(stock_codes, size=max_attempts, replace=False):
            if sampled_count >= sample_size:
                break
            if rc in seen:
                continue
            seen.add(str(rc))
            rpath = csv_map.get(str(rc))
            if rpath is None:
                continue
            if rpath not in cache:
                cache[rpath] = _load_kline(rpath)
            rr = _future_ret(
                cache[rpath],
                pd.Timestamp(row["buy_date"]),
                horizon,
                require_ma120=random_require_ma120,
            )
            if rr is None:
                continue
            sampled_count += 1
            rows.append(
                {
                    "group": "random",
                    "ts_code": str(rc),
                    "entry_date": rr["entry_date"],
                    "exit_date": rr["exit_date"],
                    "ret": rr["ret"],
                    "score": np.nan,
                }
            )

    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("no comparable returns generated")

    summary = pd.DataFrame([_summary(g, sub["ret"]) for g, sub in result.groupby("group")])
    fold = _fold_summary(result, "group")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_pool_right_tail_{label}_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    result.to_csv(os.path.join(out_dir, "returns_detail.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    fold.to_csv(os.path.join(out_dir, "fold_summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="MA120 pool right-tail study")
    p.add_argument("--label", required=True)
    p.add_argument("--panel-csv", required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--markets", default="SH,SZ")
    p.add_argument("--min-close-above-p0-days", type=int, default=0)
    p.add_argument("--min-ret-obs", type=float, default=-999.0)
    p.add_argument("--horizon", type=int, default=120)
    p.add_argument("--random-mult", type=int, default=3)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--random-require-ma120", action="store_true")
    args = p.parse_args()
    out = run(
        label=args.label,
        panel_csv=args.panel_csv,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        markets=args.markets,
        min_close_above=args.min_close_above_p0_days,
        min_ret_obs=args.min_ret_obs,
        horizon=args.horizon,
        random_mult=args.random_mult,
        seed=args.seed,
        random_require_ma120=args.random_require_ma120,
    )
    print(out)


if __name__ == "__main__":
    main()
