#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test whether 10/20/30-day pre-entry momentum identifies MA120 winners.

The outcome is the completed trade return produced by the existing MA120 ghost
rules backtest.  Features are calculated at the close immediately before the
recorded next-open entry, so the study does not use entry-day close data.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


HORIZONS = (10, 20, 30)
A_EQUITY_RE = re.compile(r"^(sh(?:60|68)\d{4}|sz(?:00|30)\d{4})$")


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def scan_symbol_files(csv_dir: str, symbols: Iterable[str]) -> Dict[str, List[str]]:
    needed = set(map(str, symbols))
    grouped: Dict[str, List[str]] = {symbol: [] for symbol in needed}
    for path in glob.glob(os.path.join(csv_dir, "**", "*"), recursive=True):
        if os.path.isfile(path):
            symbol = symbol_from_path(path)
            if symbol in needed:
                grouped[symbol].append(path)
    return {symbol: paths for symbol, paths in grouped.items() if paths}


def parse_date(raw: pd.Series) -> pd.Series:
    text = raw.astype(str).str.replace(r"\.0$", "", regex=True)
    if text.str.fullmatch(r"\d{8}").mean() > 0.8:
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(text, errors="coerce")


def load_symbol(paths: Iterable[str]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in paths:
        try:
            raw = pd.read_csv(path)
        except Exception:
            continue
        date_col = "date" if "date" in raw.columns else raw.columns[0]
        if "close" not in raw.columns:
            continue
        frame = pd.DataFrame(
            {
                "date": parse_date(raw[date_col]),
                "close": pd.to_numeric(raw["close"], errors="coerce"),
            }
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    result = result.dropna().sort_values("date").drop_duplicates("date", keep="last")
    result = result.reset_index(drop=True)
    result["ma120"] = result["close"].rolling(120, min_periods=120).mean()
    result["daily_return"] = result["close"].pct_change()
    return result


def previous_index(frame: pd.DataFrame, date: pd.Timestamp) -> Optional[int]:
    indices = frame.index[frame["date"] < date]
    return int(indices[-1]) if len(indices) else None


def last_index_on_or_before(frame: pd.DataFrame, date: pd.Timestamp) -> Optional[int]:
    indices = frame.index[frame["date"] <= date]
    return int(indices[-1]) if len(indices) else None


def build_panel(trades: pd.DataFrame, csv_dir: str) -> pd.DataFrame:
    files = scan_symbol_files(csv_dir, trades["symbol"].unique())
    rows: List[dict] = []
    for symbol, group in trades.groupby("symbol", sort=False):
        prices = load_symbol(files.get(str(symbol), []))
        if prices.empty:
            continue
        for _, trade in group.iterrows():
            asof_i = previous_index(prices, trade["entry_date"])
            exit_i = last_index_on_or_before(prices, trade["exit_date"])
            if asof_i is None or exit_i is None or asof_i < max(HORIZONS):
                continue
            row = trade.to_dict()
            row["asof_date"] = prices.at[asof_i, "date"]
            row["asof_close"] = float(prices.at[asof_i, "close"])
            row["ma120_distance"] = float(
                prices.at[asof_i, "close"] / prices.at[asof_i, "ma120"] - 1.0
            )
            for horizon in HORIZONS:
                start_i = asof_i - horizon
                trailing = prices.iloc[asof_i - horizon + 1 : asof_i + 1]
                row[f"ret_{horizon}d"] = float(
                    prices.at[asof_i, "close"] / prices.at[start_i, "close"] - 1.0
                )
                row[f"above_ma120_days_{horizon}d"] = int(
                    (trailing["close"] > trailing["ma120"]).sum()
                )
            pre_path = prices.iloc[max(0, asof_i - 30) : asof_i + 1]
            trade_path = prices.iloc[asof_i : exit_i + 1]
            row["max_abs_jump_pre30"] = float(pre_path["daily_return"].abs().max())
            row["max_abs_jump_holding"] = float(trade_path["daily_return"].abs().max())
            row["is_a_equity"] = bool(A_EQUITY_RE.fullmatch(str(symbol)))
            row["is_clean"] = bool(
                row["is_a_equity"]
                and row["max_abs_jump_pre30"] <= 0.30
                and row["max_abs_jump_holding"] <= 0.30
            )
            rows.append(row)
    return pd.DataFrame(rows)


def add_cross_section_labels(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    result["actual_top20"] = False
    result["eligible_date_group"] = False
    for _, indices in result.groupby("entry_date").groups.items():
        indices = list(indices)
        if len(indices) < 5:
            continue
        k = max(1, math.ceil(len(indices) * 0.20))
        ordered = result.loc[indices].sort_values(["ret", "symbol"], ascending=[False, True])
        result.loc[indices, "eligible_date_group"] = True
        result.loc[ordered.head(k).index, "actual_top20"] = True
    return result


def profit_factor(values: pd.Series) -> float:
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else np.nan


def overview(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset, data in (("all_matched", panel), ("clean_a_equity", panel[panel["is_clean"]])):
        returns = data["ret"]
        top_n = max(1, math.ceil(len(data) * 0.01)) if len(data) else 0
        top_contribution = returns.nlargest(top_n).sum() / returns.sum() if returns.sum() else np.nan
        rows.append(
            {
                "dataset": dataset,
                "trades": len(data),
                "symbols": data["symbol"].nunique(),
                "avg_ret": returns.mean(),
                "median_ret": returns.median(),
                "win_rate": (returns > 0).mean(),
                "profit_factor": profit_factor(returns),
                "p10": returns.quantile(0.10),
                "p90": returns.quantile(0.90),
                "p95": returns.quantile(0.95),
                "p99": returns.quantile(0.99),
                "max_ret": returns.max(),
                "top1pct_profit_contribution": top_contribution,
            }
        )
    return pd.DataFrame(rows)


def actual_winner_profile(panel: pd.DataFrame) -> pd.DataFrame:
    features = [f"ret_{h}d" for h in HORIZONS] + [
        f"above_ma120_days_{h}d" for h in HORIZONS
    ] + ["ma120_distance"]
    rows = []
    for dataset, source in (("all_matched", panel), ("clean_a_equity", panel[panel["is_clean"]])):
        data = add_cross_section_labels(source.reset_index(drop=True))
        data = data[data["eligible_date_group"]]
        for feature in features:
            winner = data.loc[data["actual_top20"], feature]
            other = data.loc[~data["actual_top20"], feature]
            rows.append(
                {
                    "dataset": dataset,
                    "feature": feature,
                    "winner_n": len(winner),
                    "winner_mean": winner.mean(),
                    "winner_median": winner.median(),
                    "other_mean": other.mean(),
                    "other_median": other.median(),
                    "median_diff": winner.median() - other.median(),
                }
            )
    return pd.DataFrame(rows)


def quintile_summary(panel: pd.DataFrame) -> pd.DataFrame:
    features = [f"ret_{h}d" for h in HORIZONS] + [
        f"above_ma120_days_{h}d" for h in HORIZONS
    ]
    rows = []
    for dataset, source in (("all_matched", panel), ("clean_a_equity", panel[panel["is_clean"]])):
        data = add_cross_section_labels(source.reset_index(drop=True))
        data = data[data["eligible_date_group"]].copy()
        for feature in features:
            ranked = data[feature].rank(method="first", pct=True)
            data["quintile"] = pd.cut(
                ranked, [0, .2, .4, .6, .8, 1.0], labels=["Q1_low", "Q2", "Q3", "Q4", "Q5_high"],
                include_lowest=True,
            )
            for quintile, group in data.groupby("quintile", observed=False):
                returns = group["ret"]
                rows.append(
                    {
                        "dataset": dataset,
                        "feature": feature,
                        "quintile": str(quintile),
                        "trades": len(group),
                        "feature_median": group[feature].median(),
                        "actual_top20_rate": group["actual_top20"].mean(),
                        "avg_ret": returns.mean(),
                        "median_ret": returns.median(),
                        "win_rate": (returns > 0).mean(),
                        "profit_factor": profit_factor(returns),
                        "tail_gt20": (returns >= 0.20).mean(),
                    }
                )
    return pd.DataFrame(rows)


def choose_top20(group: pd.DataFrame, score_col: str) -> pd.Index:
    k = max(1, math.ceil(len(group) * 0.20))
    return group.sort_values([score_col, "symbol"], ascending=[False, True]).head(k).index


def selection_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    base_features = [f"ret_{h}d" for h in HORIZONS] + [
        f"above_ma120_days_{h}d" for h in HORIZONS
    ]
    rows = []
    for dataset, source in (("all_matched", panel), ("clean_a_equity", panel[panel["is_clean"]])):
        data = add_cross_section_labels(source.reset_index(drop=True))
        data = data[data["eligible_date_group"]].copy()
        for feature in base_features:
            data[f"pct_{feature}"] = data.groupby("entry_date")[feature].rank(pct=True, method="average")
        data["momentum_composite"] = data[[f"pct_ret_{h}d" for h in HORIZONS]].mean(axis=1)
        data["all6_composite"] = data[[f"pct_{f}" for f in base_features]].mean(axis=1)
        selectors = base_features + ["momentum_composite", "all6_composite"]
        dates = sorted(data["entry_date"].drop_duplicates())
        split_date = dates[math.floor(len(dates) * 0.70)] if dates else pd.NaT
        periods = {
            "all": data,
            "early70": data[data["entry_date"] < split_date],
            "late30": data[data["entry_date"] >= split_date],
        }
        for period, period_data in periods.items():
            if period_data.empty:
                continue
            for selector in selectors:
                selected_indices: List[int] = []
                for _, group in period_data.groupby("entry_date"):
                    selected_indices.extend(choose_top20(group, selector).tolist())
                selected = period_data.loc[selected_indices]
                precision = selected["actual_top20"].mean()
                returns = selected["ret"]
                rows.append(
                    {
                        "dataset": dataset,
                        "period": period,
                        "split_date": split_date,
                        "selector": selector,
                        "selected_trades": len(selected),
                        "top20_precision": precision,
                        "lift_vs_random": precision / period_data["actual_top20"].mean(),
                        "avg_ret": returns.mean(),
                        "median_ret": returns.median(),
                        "win_rate": (returns > 0).mean(),
                        "profit_factor": profit_factor(returns),
                        "tail_gt20": (returns >= 0.20).mean(),
                    }
                )
    return pd.DataFrame(rows)


def rank_ic_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarize same-entry-date Spearman rank IC, including time stability."""
    features = [f"ret_{h}d" for h in HORIZONS] + [
        f"above_ma120_days_{h}d" for h in HORIZONS
    ]
    rows = []
    for dataset, source in (("all_matched", panel), ("clean_a_equity", panel[panel["is_clean"]])):
        data = source.copy()
        eligible_dates = data.groupby("entry_date").size()
        eligible_dates = sorted(eligible_dates[eligible_dates >= 5].index)
        split_date = eligible_dates[math.floor(len(eligible_dates) * 0.70)] if eligible_dates else pd.NaT
        for feature in features:
            daily_rows = []
            for date, group in data[data["entry_date"].isin(eligible_dates)].groupby("entry_date"):
                ic = group[[feature, "ret"]].corr(method="spearman").iloc[0, 1]
                if np.isfinite(ic):
                    daily_rows.append((date, float(ic)))
            daily = pd.DataFrame(daily_rows, columns=["entry_date", "rank_ic"])
            for period, values in (
                ("all", daily["rank_ic"]),
                ("early70", daily.loc[daily["entry_date"] < split_date, "rank_ic"]),
                ("late30", daily.loc[daily["entry_date"] >= split_date, "rank_ic"]),
            ):
                std = values.std(ddof=1)
                rows.append(
                    {
                        "dataset": dataset,
                        "period": period,
                        "split_date": split_date,
                        "feature": feature,
                        "dates": len(values),
                        "mean_rank_ic": values.mean(),
                        "median_rank_ic": values.median(),
                        "positive_ic_rate": (values > 0).mean(),
                        "t_stat": values.mean() / (std / math.sqrt(len(values)))
                        if len(values) > 1 and std > 0
                        else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def winner_examples(panel: pd.DataFrame) -> pd.DataFrame:
    clean = add_cross_section_labels(panel[panel["is_clean"]].reset_index(drop=True))
    columns = [
        "symbol", "entry_date", "exit_date", "ret", "holding_days", "exit_reason",
        "ret_10d", "ret_20d", "ret_30d", "above_ma120_days_30d", "ma120_distance",
    ]
    return clean[clean["actual_top20"]].sort_values("ret", ascending=False)[columns].head(100)


def run(args: argparse.Namespace) -> str:
    trades = pd.read_csv(args.trades_csv)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"], errors="coerce")
    trades["exit_date"] = pd.to_datetime(trades["exit_date"], errors="coerce")
    trades = trades[
        (trades["window"] == 120)
        & (trades["mode"] == "ghost")
        & (trades["exit_reason"] != "open_end")
    ].copy()
    panel = build_panel(trades, args.csv_dir)
    panel = add_cross_section_labels(panel)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(args.output_root, f"ma120_ghost_top20_momentum_{stamp}")
    os.makedirs(output_dir, exist_ok=True)
    outputs = {
        "feature_panel.csv": panel,
        "overview.csv": overview(panel),
        "actual_winner_profile.csv": actual_winner_profile(panel),
        "feature_quintiles.csv": quintile_summary(panel),
        "selection_metrics.csv": selection_metrics(panel),
        "rank_ic_summary.csv": rank_ic_summary(panel),
        "top20_winner_examples.csv": winner_examples(panel),
    }
    for filename, frame in outputs.items():
        frame.to_csv(os.path.join(output_dir, filename), index=False, encoding="utf-8-sig")
    print(output_dir)
    print("\nOverview")
    print(outputs["overview.csv"].to_string(index=False))
    print("\nAll-period clean selection metrics")
    selection = outputs["selection_metrics.csv"]
    print(selection[(selection["dataset"] == "clean_a_equity") & (selection["period"] == "all")].to_string(index=False))
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trades-csv",
        default="cy_quant/output/ma_trend_ghost_rules_a_20260811_095118/trades.csv",
    )
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output-root", default="cy_quant/output")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
