"""MA120 breakthrough event scoring and grouped validation.

Research goal:
1) Find fresh MA120 breakthrough events.
2) Observe next 30 trading days to score stability/strength.
3) Group events by score quantiles and compare forward returns.
"""

from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


@dataclass
class ValidationConfig:
    csv_dir: str = os.path.expanduser("~/abu/data/csv")
    output_dir: str = "cy_quant/output"
    prefixes: tuple[str, ...] = ("sh", "sz")
    obs_days: int = 30
    pre_high_lookback: int = 120
    cooldown_days: int = 60
    horizons: tuple[int, ...] = (30, 60, 120)
    min_rows_for_ma120: int = 260
    quantiles: int = 5
    max_stocks: Optional[int] = None
    ma_slope_lookback: int = 20
    min_close_above_p0_days: int = 18
    train_ratio: float = 0.7
    industry_cap_per_month: Optional[int] = None
    require_multi_tf_up: bool = False
    multi_tf_bonus: float = 8.0


def _parse_filename(path: str) -> Optional[str]:
    base = os.path.basename(path)
    stem = base[:-4] if base.endswith(".csv") else base
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    code_part = parts[0]
    if len(code_part) < 8:
        return None
    prefix = code_part[:2].lower()
    code = code_part[2:]
    market_map = {"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}
    market = market_map.get(prefix)
    if market is None:
        return None
    return f"{code}.{market}"


def _load_stock_industry_map(csv_dir: str) -> Dict[str, str]:
    # Reuse local Tushare stock basic cache when available.
    candidates = [
        os.path.expanduser("~/abu/tushare/finance/stock_basic_all.csv"),
        os.path.expanduser("~/abu/tushare/stock_list/stock_basic_list_20260329.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            df = pd.read_csv(p, usecols=lambda c: c in {"ts_code", "industry"})
            df = df.dropna(subset=["ts_code"]).drop_duplicates("ts_code")
            if "industry" not in df.columns:
                df["industry"] = "UNKNOWN"
            return dict(zip(df["ts_code"], df["industry"].fillna("UNKNOWN")))
    return {}


def _list_stock_files(config: ValidationConfig) -> List[str]:
    files: List[str] = []
    for prefix in config.prefixes:
        files.extend(glob.glob(os.path.join(config.csv_dir, f"{prefix}*")))
        files.extend(glob.glob(os.path.join(config.csv_dir, f"{prefix}*.csv")))
    files = sorted(set(files))
    if config.max_stocks is not None and len(files) > config.max_stocks:
        positions = np.linspace(0, len(files) - 1, config.max_stocks, dtype=int)
        files = [files[i] for i in positions]
    return files


def _load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=lambda c: c in {"date", "open", "high", "low", "close", "pre_close", "volume"})
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["date"].astype(str), format="%Y%m%d", errors="coerce")
    for col in ["open", "high", "low", "close", "pre_close", "volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["trade_date", "close", "high", "low"]).sort_values("trade_date").reset_index(drop=True)
    return out


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ma20"] = out["close"].rolling(window=20, min_periods=20).mean()
    out["ma60"] = out["close"].rolling(window=60, min_periods=60).mean()
    out["ma120"] = out["close"].rolling(window=120, min_periods=120).mean()
    out["ma20_slope"] = out["ma20"] - out["ma20"].shift(20)
    out["ma60_slope"] = out["ma60"] - out["ma60"].shift(20)
    out["ma120_slope"] = out["ma120"] - out["ma120"].shift(20)
    prev_close = out["close"].shift(1)
    tr1 = out["high"] - out["low"]
    tr2 = (out["high"] - prev_close).abs()
    tr3 = (out["low"] - prev_close).abs()
    out["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["atr14"] = out["tr"].rolling(window=14, min_periods=14).mean()
    out["atr14_pct"] = out["atr14"] / out["close"]
    if "volume" in out.columns:
        out["vol_ma20"] = out["volume"].rolling(window=20, min_periods=20).mean()
        out["volume_ratio"] = out["volume"] / out["vol_ma20"]
    else:
        out["volume_ratio"] = np.nan
    return out


def _build_weekly_monthly_trend_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Attach weekly/monthly trend flags back to daily rows by date."""
    work = df[["trade_date", "close"]].copy().sort_values("trade_date")
    work["week"] = work["trade_date"].dt.to_period("W").apply(lambda p: p.end_time.normalize())
    work["month"] = work["trade_date"].dt.to_period("M").dt.to_timestamp("M")

    # Weekly close and slope
    w = work.groupby("week", as_index=False).tail(1)[["week", "close"]].rename(columns={"close": "w_close"})
    w["w_ma20"] = w["w_close"].rolling(20, min_periods=20).mean()
    w["w_ma20_slope"] = w["w_ma20"] - w["w_ma20"].shift(4)
    w["w_up"] = w["w_ma20_slope"] > 0

    # Monthly close and slope
    m = work.groupby("month", as_index=False).tail(1)[["month", "close"]].rename(columns={"close": "m_close"})
    m["m_ma10"] = m["m_close"].rolling(10, min_periods=10).mean()
    m["m_ma10_slope"] = m["m_ma10"] - m["m_ma10"].shift(3)
    m["m_up"] = m["m_ma10_slope"] > 0

    out = work.merge(w[["week", "w_up"]], on="week", how="left").merge(m[["month", "m_up"]], on="month", how="left")
    out["multi_tf_up"] = out["w_up"].fillna(False) & out["m_up"].fillna(False)
    return out[["trade_date", "w_up", "m_up", "multi_tf_up"]]


def _score_event(
    event_df: pd.DataFrame,
    p0_close: float,
    pre120_high: float,
    ma20_slope: float,
    ma60_slope: float,
    ma120_slope: float,
    w_up: bool,
    m_up: bool,
    multi_tf_bonus: float,
) -> Dict[str, float]:
    obs_len = len(event_df)
    rets = event_df["close"].pct_change().fillna(0.0)
    up = rets[rets > 0]
    down = rets[rets < 0]

    above_ma120_days = int((event_df["close"] > event_df["ma120"]).sum())
    close_above_p0_days = int((event_df["close"] > p0_close).sum())
    up_days = int((rets > 0).sum())
    down_days = int((rets < 0).sum())
    sum_up_pct = float(up.sum())
    sum_down_abs_pct = float((-down).sum())

    running_dd = event_df["close"] / p0_close - 1.0
    max_drawdown_from_p0 = float(running_dd.min())

    break_pre120_high_count = int((event_df["close"] > pre120_high).sum())
    break_idx = np.where((event_df["close"] > pre120_high).to_numpy())[0]
    first_break_pre120_high_day = int(break_idx[0] + 1) if len(break_idx) else np.nan

    atr_mean_pct = float(event_df["atr14_pct"].mean()) if "atr14_pct" in event_df.columns else np.nan
    vol_ratio_mean = float(pd.to_numeric(event_df.get("volume_ratio"), errors="coerce").mean())
    ret_30d = float(event_df.iloc[-1]["close"] / p0_close - 1.0)

    # 持续上涨为主，涨幅作为次要加分
    trend_score = (above_ma120_days / obs_len) * 18 + (close_above_p0_days / obs_len) * 17
    if ret_30d <= 0:
        growth_score = 0
    elif ret_30d <= 0.05:
        growth_score = 3
    elif ret_30d <= 0.10:
        growth_score = 7
    elif ret_30d <= 0.20:
        growth_score = 12
    else:
        growth_score = 15
    updown_ratio = min(sum_up_pct / max(sum_down_abs_pct, 1e-6), 3.0)
    up_structure_score = (up_days / obs_len) * 10 + (updown_ratio / 3.0) * 10

    dd_abs_pct = abs(max_drawdown_from_p0) * 100
    if dd_abs_pct <= 3:
        drawdown_score = 20
    elif dd_abs_pct <= 5:
        drawdown_score = 16
    elif dd_abs_pct <= 8:
        drawdown_score = 10
    elif dd_abs_pct <= 12:
        drawdown_score = 5
    else:
        drawdown_score = 0

    if np.isnan(first_break_pre120_high_day):
        timing_score = 0
    elif first_break_pre120_high_day <= 10:
        timing_score = 10
    elif first_break_pre120_high_day <= 20:
        timing_score = 6
    else:
        timing_score = 3
    new_high_score = (break_pre120_high_count / obs_len) * 10 + timing_score

    atr_pct = atr_mean_pct * 100 if pd.notna(atr_mean_pct) else 999
    if atr_pct <= 3:
        vol_score = 10
    elif atr_pct <= 5:
        vol_score = 7
    elif atr_pct <= 8:
        vol_score = 4
    else:
        vol_score = 0

    # 均线斜率结构作为加分项，不再做硬过滤。
    if ma20_slope > ma60_slope > ma120_slope > 0:
        slope_structure_score = 8
    elif ma20_slope > ma60_slope > 0:
        slope_structure_score = 5
    elif ma20_slope > 0 and ma60_slope > 0 and ma120_slope > 0:
        slope_structure_score = 3
    else:
        slope_structure_score = 0

    multi_tf_score = 0.0
    if w_up and m_up:
        multi_tf_score = multi_tf_bonus
    elif w_up or m_up:
        multi_tf_score = multi_tf_bonus * 0.5

    total_score = (
        trend_score
        + growth_score
        + up_structure_score
        + drawdown_score
        + new_high_score
        + vol_score
        + slope_structure_score
        + multi_tf_score
    )
    return {
        "above_ma120_days": above_ma120_days,
        "close_above_p0_days": close_above_p0_days,
        "up_days": up_days,
        "down_days": down_days,
        "sum_up_pct": sum_up_pct,
        "sum_down_abs_pct": sum_down_abs_pct,
        "max_drawdown_from_p0": max_drawdown_from_p0,
        "break_pre120_high_count": break_pre120_high_count,
        "first_break_pre120_high_day": first_break_pre120_high_day,
        "atr_mean_pct": atr_mean_pct,
        "vol_ratio_mean_30d": vol_ratio_mean,
        "ret_30d_from_p0": ret_30d,
        "trend_score": trend_score,
        "growth_score": growth_score,
        "up_structure_score": up_structure_score,
        "drawdown_score": drawdown_score,
        "new_high_score": new_high_score,
        "vol_score": vol_score,
        "slope_structure_score": slope_structure_score,
        "multi_tf_score": multi_tf_score,
        "total_score": total_score,
    }


def _extract_events_for_stock(ts_code: str, path: str, config: ValidationConfig) -> List[Dict[str, object]]:
    df = _load_kline(path)
    if df.empty or len(df) < config.min_rows_for_ma120:
        return []
    df = _add_indicators(df)
    tf_flags = _build_weekly_monthly_trend_flags(df)
    df = df.merge(tf_flags, on="trade_date", how="left")
    df["above_ma120"] = df["close"] > df["ma120"]

    events: List[Dict[str, object]] = []
    last_event_idx = -10_000
    max_h = max(config.horizons)
    min_start = max(120, config.pre_high_lookback)
    for i in range(min_start, len(df) - config.obs_days - max_h - 1):
        if i - last_event_idx < config.cooldown_days:
            continue
        if pd.isna(df.at[i, "ma120"]) or pd.isna(df.at[i - 1, "ma120"]):
            continue
        # Fresh breakthrough event P0: yesterday below/equal, today above.
        if not (bool(df.at[i, "above_ma120"]) and not bool(df.at[i - 1, "above_ma120"])):
            continue
        # MA120 must be rising.
        lb = config.ma_slope_lookback
        if i - lb < 0 or pd.isna(df.at[i - lb, "ma120"]) or pd.isna(df.at[i, "ma120"]):
            continue
        if not (df.at[i, "ma120"] > df.at[i - lb, "ma120"]):
            continue
        if config.require_multi_tf_up and not bool(df.at[i, "multi_tf_up"]):
            continue
        # MA slope structure is scored later, not a hard filter.
        ma20_slope = df.at[i, "ma20_slope"]
        ma60_slope = df.at[i, "ma60_slope"]
        ma120_slope = df.at[i, "ma120_slope"]
        if pd.isna(ma20_slope) or pd.isna(ma60_slope) or pd.isna(ma120_slope):
            continue

        p0_close = float(df.at[i, "close"])
        pre120_high = float(df.iloc[i - config.pre_high_lookback : i]["high"].max())
        obs_df = df.iloc[i + 1 : i + 1 + config.obs_days].copy()
        if len(obs_df) < config.obs_days:
            continue

        event = {
            "ts_code": ts_code,
            "p0_date": df.at[i, "trade_date"],
            "p0_close": p0_close,
            "pre120_high": pre120_high,
            "eval_date": df.at[i + config.obs_days, "trade_date"],
            "w_up": bool(df.at[i, "w_up"]) if pd.notna(df.at[i, "w_up"]) else False,
            "m_up": bool(df.at[i, "m_up"]) if pd.notna(df.at[i, "m_up"]) else False,
            "multi_tf_up": bool(df.at[i, "multi_tf_up"]) if pd.notna(df.at[i, "multi_tf_up"]) else False,
        }
        event.update(
            _score_event(
                obs_df,
                p0_close,
                pre120_high,
                float(ma20_slope),
                float(ma60_slope),
                float(ma120_slope),
                bool(df.at[i, "w_up"]) if pd.notna(df.at[i, "w_up"]) else False,
                bool(df.at[i, "m_up"]) if pd.notna(df.at[i, "m_up"]) else False,
                config.multi_tf_bonus,
            )
        )

        buy_idx = i + config.obs_days + 1
        buy_close = float(df.at[buy_idx, "close"])
        event["buy_date"] = df.at[buy_idx, "trade_date"]
        event["buy_close"] = buy_close

        for h in config.horizons:
            end_idx = buy_idx + h
            end_close = float(df.at[end_idx, "close"])
            event[f"ret_{h}d"] = end_close / buy_close - 1.0
            event[f"sell_date_{h}d"] = df.at[end_idx, "trade_date"]
            window = df.iloc[buy_idx : end_idx + 1]
            event[f"max_dd_{h}d"] = float((window["close"] / buy_close - 1.0).min())
            event[f"break_ma120_ratio_{h}d"] = float((window["close"] < window["ma120"]).mean())

        events.append(event)
        last_event_idx = i

    return events


def build_event_panel(config: ValidationConfig) -> pd.DataFrame:
    files = _list_stock_files(config)
    rows: List[Dict[str, object]] = []
    industry_map = _load_stock_industry_map(config.csv_dir)
    for path in files:
        ts_code = _parse_filename(path)
        if ts_code is None or not ts_code.endswith((".SH", ".SZ", ".BJ", ".HK", ".US")):
            continue
        if not ts_code.endswith((".SH", ".SZ")):
            continue
        rows.extend(_extract_events_for_stock(ts_code, path, config))
    if not rows:
        return pd.DataFrame()
    panel = pd.DataFrame(rows).sort_values(["eval_date", "total_score"], ascending=[True, False]).reset_index(drop=True)
    if not panel.empty:
        panel["industry"] = panel["ts_code"].map(industry_map).fillna("UNKNOWN")
    return panel


def apply_industry_cap(panel: pd.DataFrame, cap: Optional[int]) -> pd.DataFrame:
    if cap is None or panel.empty:
        return panel
    out = panel.copy()
    out["eval_month"] = pd.to_datetime(out["eval_date"]).dt.to_period("M").dt.to_timestamp("M")
    out = out.sort_values(["eval_month", "total_score"], ascending=[True, False])
    out = out.groupby(["eval_month", "industry"], group_keys=False).head(cap)
    return out.drop(columns=["eval_month"])


def summarize_by_score_quantile(panel: pd.DataFrame, quantiles: int, horizons: Iterable[int]) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    bins = min(quantiles, panel["total_score"].nunique())
    groups = pd.qcut(panel["total_score"], q=bins, labels=False, duplicates="drop") + 1
    tagged = panel.assign(score_group=groups)
    agg: Dict[str, object] = {"ts_code": "count", "total_score": "mean"}
    for h in horizons:
        agg[f"ret_{h}d"] = "mean"
        agg[f"max_dd_{h}d"] = "mean"
        agg[f"break_ma120_ratio_{h}d"] = "mean"
    out = tagged.groupby("score_group").agg(agg).rename(columns={"ts_code": "events", "total_score": "avg_score"})
    return out.round(4)


def summarize_monthly_top(panel: pd.DataFrame, top_n: int, horizons: Iterable[int]) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    panel = panel.copy()
    panel["eval_month"] = pd.to_datetime(panel["eval_date"]).dt.to_period("M").dt.to_timestamp("M")
    rows: List[Dict[str, object]] = []
    for month, g in panel.groupby("eval_month"):
        top = g.sort_values("total_score", ascending=False).head(top_n)
        row: Dict[str, object] = {"eval_month": month, "events": int(len(top)), "avg_score": float(top["total_score"].mean())}
        for h in horizons:
            row[f"ret_{h}d"] = float(top[f"ret_{h}d"].mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("eval_month")


def summarize_monthly_top_with_gate(
    panel: pd.DataFrame,
    top_n: int,
    horizons: Iterable[int],
    min_close_above_p0_days: int,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    panel = panel.copy()
    panel["eval_month"] = pd.to_datetime(panel["eval_date"]).dt.to_period("M").dt.to_timestamp("M")
    rows: List[Dict[str, object]] = []
    for month, g in panel.groupby("eval_month"):
        gated = g[(g["ret_30d_from_p0"] > 0) & (g["close_above_p0_days"] >= min_close_above_p0_days)].copy()
        if gated.empty:
            continue
        top = gated.sort_values("total_score", ascending=False).head(top_n)
        row: Dict[str, object] = {
            "eval_month": month,
            "events": int(len(top)),
            "avg_score": float(top["total_score"].mean()),
            "avg_ret_30d_from_p0": float(top["ret_30d_from_p0"].mean()),
            "avg_close_above_p0_days": float(top["close_above_p0_days"].mean()),
        }
        for h in horizons:
            row[f"ret_{h}d"] = float(top[f"ret_{h}d"].mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("eval_month")


def summarize_monthly_top_with_dual_gate(
    panel: pd.DataFrame,
    top_n: int,
    horizons: Iterable[int],
    min_close_above_p0_days: int,
    min_ret_30d_from_p0: float,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    panel = panel.copy()
    panel["eval_month"] = pd.to_datetime(panel["eval_date"]).dt.to_period("M").dt.to_timestamp("M")
    rows: List[Dict[str, object]] = []
    for month, g in panel.groupby("eval_month"):
        gated = g[
            (g["ret_30d_from_p0"] > min_ret_30d_from_p0)
            & (g["close_above_p0_days"] >= min_close_above_p0_days)
        ].copy()
        if gated.empty:
            continue
        top = gated.sort_values("total_score", ascending=False).head(top_n)
        row: Dict[str, object] = {
            "eval_month": month,
            "events": int(len(top)),
            "avg_score": float(top["total_score"].mean()),
            "avg_ret_30d_from_p0": float(top["ret_30d_from_p0"].mean()),
            "avg_close_above_p0_days": float(top["close_above_p0_days"].mean()),
        }
        for h in horizons:
            row[f"ret_{h}d"] = float(top[f"ret_{h}d"].mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("eval_month")


def gate_grid_search(
    panel: pd.DataFrame,
    top_n: int,
    horizons: Iterable[int],
    day_thresholds: Iterable[int],
    ret_thresholds: Iterable[float],
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for day_th in day_thresholds:
        for ret_th in ret_thresholds:
            monthly = summarize_monthly_top_with_dual_gate(
                panel=panel,
                top_n=top_n,
                horizons=horizons,
                min_close_above_p0_days=day_th,
                min_ret_30d_from_p0=ret_th,
            )
            if monthly.empty:
                continue
            row: Dict[str, object] = {
                "min_close_above_p0_days": int(day_th),
                "min_ret_30d_from_p0": float(ret_th),
                "months": int(len(monthly)),
                "avg_events_per_month": float(monthly["events"].mean()),
            }
            for h in horizons:
                row[f"ret_{h}d_mean"] = float(monthly[f"ret_{h}d"].mean())
                row[f"ret_{h}d_std"] = float(monthly[f"ret_{h}d"].std(ddof=0))
            # A simple stability score: reward long-horizon mean, penalize volatility and too few samples.
            row["stability_score"] = (
                row.get("ret_120d_mean", 0.0)
                - 0.5 * row.get("ret_120d_std", 0.0)
                + 0.1 * row.get("ret_60d_mean", 0.0)
                + 0.001 * min(row["months"], 24)
                + 0.001 * min(row["avg_events_per_month"], 30)
            )
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(
        ["stability_score", "ret_120d_mean", "months", "avg_events_per_month"],
        ascending=[False, False, False, False],
    )
    return out


def _split_train_valid_by_time(panel: pd.DataFrame, train_ratio: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if panel.empty:
        return panel.copy(), panel.copy()
    dated = panel.copy()
    dated["eval_date"] = pd.to_datetime(dated["eval_date"])
    unique_dates = np.array(sorted(dated["eval_date"].dropna().unique()))
    if len(unique_dates) < 4:
        return dated.copy(), pd.DataFrame(columns=dated.columns)
    cut_idx = max(1, min(len(unique_dates) - 1, int(len(unique_dates) * train_ratio)))
    cut_date = unique_dates[cut_idx - 1]
    train = dated[dated["eval_date"] <= cut_date].copy()
    valid = dated[dated["eval_date"] > cut_date].copy()
    return train, valid


def _winner_loser_feature_diff(train: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "ret_30d_from_p0",
        "close_above_p0_days",
        "above_ma120_days",
        "max_drawdown_from_p0",
        "break_pre120_high_count",
        "first_break_pre120_high_day",
        "atr_mean_pct",
        "sum_up_pct",
        "sum_down_abs_pct",
    ]
    data = train.dropna(subset=["ret_120d"]).copy()
    if data.empty:
        return pd.DataFrame()
    hi = data["ret_120d"].quantile(0.8)
    lo = data["ret_120d"].quantile(0.2)
    winners = data[data["ret_120d"] >= hi]
    losers = data[data["ret_120d"] <= lo]
    rows = []
    for c in cols:
        if c not in data.columns:
            continue
        w = pd.to_numeric(winners[c], errors="coerce")
        l = pd.to_numeric(losers[c], errors="coerce")
        rows.append(
            {
                "feature": c,
                "winner_median": float(w.median()) if not w.empty else np.nan,
                "loser_median": float(l.median()) if not l.empty else np.nan,
                "winner_mean": float(w.mean()) if not w.empty else np.nan,
                "loser_mean": float(l.mean()) if not l.empty else np.nan,
                "median_diff": float(w.median() - l.median()) if (not w.empty and not l.empty) else np.nan,
            }
        )
    out = pd.DataFrame(rows).sort_values("median_diff", ascending=False)
    return out


def _derive_candidate_rule(diff: pd.DataFrame) -> Dict[str, float]:
    # Keep a simple robust rule from key features using midpoint between winner/loser medians.
    lookup = diff.set_index("feature")
    def midpoint(feature: str, fallback: float) -> float:
        if feature not in lookup.index:
            return fallback
        wm = lookup.at[feature, "winner_median"]
        lm = lookup.at[feature, "loser_median"]
        if pd.isna(wm) or pd.isna(lm):
            return fallback
        return float((wm + lm) / 2.0)
    return {
        "min_ret_30d_from_p0": max(0.0, midpoint("ret_30d_from_p0", 0.0)),
        "min_close_above_p0_days": int(round(max(10, min(28, midpoint("close_above_p0_days", 15))))),
        "min_break_pre120_high_count": int(round(max(0, min(30, midpoint("break_pre120_high_count", 2))))),
        "max_drawdown_from_p0": float(min(-0.02, midpoint("max_drawdown_from_p0", -0.08))),
    }


def apply_candidate_rule(panel: pd.DataFrame, rule: Dict[str, float]) -> pd.DataFrame:
    if panel.empty:
        return panel.copy()
    out = panel.copy()
    return out[
        (out["ret_30d_from_p0"] > rule["min_ret_30d_from_p0"])
        & (out["close_above_p0_days"] >= rule["min_close_above_p0_days"])
        & (out["break_pre120_high_count"] >= rule["min_break_pre120_high_count"])
        & (out["max_drawdown_from_p0"] >= rule["max_drawdown_from_p0"])
    ].copy()


def summarize_slice(label: str, panel: pd.DataFrame, horizons: Iterable[int]) -> Dict[str, object]:
    row: Dict[str, object] = {"slice": label, "events": int(len(panel))}
    if panel.empty:
        for h in horizons:
            row[f"ret_{h}d_mean"] = np.nan
            row[f"ret_{h}d_win"] = np.nan
        return row
    for h in horizons:
        s = pd.to_numeric(panel[f"ret_{h}d"], errors="coerce")
        row[f"ret_{h}d_mean"] = float(s.mean())
        row[f"ret_{h}d_win"] = float((s > 0).mean())
    return row


def rolling_gate_validation(
    panel: pd.DataFrame,
    horizons: Iterable[int],
    day_thresholds: Iterable[int],
    ret_thresholds: Iterable[float],
    folds: int = 3,
    min_train_dates: int = 6,
    min_valid_dates: int = 3,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    work = panel.copy()
    work["eval_date"] = pd.to_datetime(work["eval_date"])
    dates = np.array(sorted(work["eval_date"].dropna().unique()))
    if len(dates) < (min_train_dates + min_valid_dates + folds):
        return pd.DataFrame()

    rows: List[Dict[str, object]] = []
    # expanding train + fixed forward validation windows
    for fold in range(folds):
        train_end_idx = min_train_dates + fold * max(1, (len(dates) - min_train_dates - min_valid_dates) // max(folds - 1, 1))
        valid_end_idx = min(len(dates), train_end_idx + min_valid_dates)
        train_dates = dates[:train_end_idx]
        valid_dates = dates[train_end_idx:valid_end_idx]
        if len(valid_dates) < min_valid_dates:
            continue
        train = work[work["eval_date"].isin(train_dates)].copy()
        valid = work[work["eval_date"].isin(valid_dates)].copy()
        base_train_120 = float(train["ret_120d"].mean()) if not train.empty else np.nan
        base_valid_120 = float(valid["ret_120d"].mean()) if not valid.empty else np.nan
        for day_th in day_thresholds:
            for ret_th in ret_thresholds:
                train_hit = apply_candidate_rule(
                    train,
                    {
                        "min_ret_30d_from_p0": float(ret_th),
                        "min_close_above_p0_days": int(day_th),
                        "min_break_pre120_high_count": 0,
                        "max_drawdown_from_p0": -1.0,
                    },
                )
                valid_hit = apply_candidate_rule(
                    valid,
                    {
                        "min_ret_30d_from_p0": float(ret_th),
                        "min_close_above_p0_days": int(day_th),
                        "min_break_pre120_high_count": 0,
                        "max_drawdown_from_p0": -1.0,
                    },
                )
                r = {
                    "fold": fold + 1,
                    "min_close_above_p0_days": int(day_th),
                    "min_ret_30d_from_p0": float(ret_th),
                    "train_events": int(len(train_hit)),
                    "valid_events": int(len(valid_hit)),
                    "base_train_ret120": base_train_120,
                    "base_valid_ret120": base_valid_120,
                    "train_ret120": float(train_hit["ret_120d"].mean()) if not train_hit.empty else np.nan,
                    "valid_ret120": float(valid_hit["ret_120d"].mean()) if not valid_hit.empty else np.nan,
                    "valid_win120": float((valid_hit["ret_120d"] > 0).mean()) if not valid_hit.empty else np.nan,
                    "valid_dd120": float(valid_hit["max_dd_120d"].mean()) if not valid_hit.empty else np.nan,
                }
                r["train_alpha120"] = r["train_ret120"] - base_train_120 if pd.notna(r["train_ret120"]) and pd.notna(base_train_120) else np.nan
                r["valid_alpha120"] = r["valid_ret120"] - base_valid_120 if pd.notna(r["valid_ret120"]) and pd.notna(base_valid_120) else np.nan
                r["valid_eff120"] = (
                    (r["valid_ret120"] / abs(r["valid_dd120"]))
                    if pd.notna(r["valid_ret120"]) and pd.notna(r["valid_dd120"]) and r["valid_dd120"] != 0
                    else np.nan
                )
                rows.append(r)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def summarize_rolling_stability(rolling_df: pd.DataFrame, min_valid_events: int = 5) -> pd.DataFrame:
    if rolling_df.empty:
        return pd.DataFrame()
    df = rolling_df.copy()
    # valid fold means enough signals and positive alpha
    df["is_effective_fold"] = (
        (df["valid_events"] >= min_valid_events)
        & (df["valid_alpha120"] > 0)
    )
    grouped = df.groupby(["min_close_above_p0_days", "min_ret_30d_from_p0"], as_index=False).agg(
        folds=("fold", "count"),
        effective_folds=("is_effective_fold", "sum"),
        avg_valid_events=("valid_events", "mean"),
        avg_valid_alpha120=("valid_alpha120", "mean"),
        avg_valid_ret120=("valid_ret120", "mean"),
        avg_valid_eff120=("valid_eff120", "mean"),
        avg_valid_win120=("valid_win120", "mean"),
    )
    grouped["effective_ratio"] = grouped["effective_folds"] / grouped["folds"]
    grouped["stable_flag"] = grouped["effective_folds"] >= 2
    grouped = grouped.sort_values(
        ["stable_flag", "effective_folds", "avg_valid_alpha120", "avg_valid_events"],
        ascending=[False, False, False, False],
    )
    return grouped


def apply_extended_daily_rule(
    panel: pd.DataFrame,
    min_ret_30d_from_p0: float,
    min_close_above_p0_days: int,
    max_atr_mean_pct: float,
    min_vol_ratio_mean_30d: float,
    min_max_drawdown_from_p0: float,
) -> pd.DataFrame:
    if panel.empty:
        return panel.copy()
    out = panel.copy()
    return out[
        (out["ret_30d_from_p0"] > min_ret_30d_from_p0)
        & (out["close_above_p0_days"] >= min_close_above_p0_days)
        & (out["atr_mean_pct"] <= max_atr_mean_pct)
        & (out["vol_ratio_mean_30d"] >= min_vol_ratio_mean_30d)
        & (out["max_drawdown_from_p0"] >= min_max_drawdown_from_p0)
    ].copy()


def rolling_extended_feature_validation(
    panel: pd.DataFrame,
    folds: int = 3,
    min_train_dates: int = 6,
    min_valid_dates: int = 3,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    work = panel.copy()
    work["eval_date"] = pd.to_datetime(work["eval_date"])
    dates = np.array(sorted(work["eval_date"].dropna().unique()))
    if len(dates) < (min_train_dates + min_valid_dates + folds):
        return pd.DataFrame()

    rows: List[Dict[str, object]] = []
    day_ths = [15, 18]
    ret_ths = [0.0, 0.03]
    atr_maxs = [0.04, 0.05, 0.06]
    vol_mins = [0.95, 1.05, 1.15]
    dd_mins = [-0.12, -0.08]

    for fold in range(folds):
        train_end_idx = min_train_dates + fold * max(1, (len(dates) - min_train_dates - min_valid_dates) // max(folds - 1, 1))
        valid_end_idx = min(len(dates), train_end_idx + min_valid_dates)
        train_dates = dates[:train_end_idx]
        valid_dates = dates[train_end_idx:valid_end_idx]
        if len(valid_dates) < min_valid_dates:
            continue
        train = work[work["eval_date"].isin(train_dates)].copy()
        valid = work[work["eval_date"].isin(valid_dates)].copy()
        base_valid_120 = float(valid["ret_120d"].mean()) if not valid.empty else np.nan
        for d in day_ths:
            for r in ret_ths:
                for a in atr_maxs:
                    for v in vol_mins:
                        for dd in dd_mins:
                            valid_hit = apply_extended_daily_rule(
                                valid,
                                min_ret_30d_from_p0=r,
                                min_close_above_p0_days=d,
                                max_atr_mean_pct=a,
                                min_vol_ratio_mean_30d=v,
                                min_max_drawdown_from_p0=dd,
                            )
                            valid_ret = float(valid_hit["ret_120d"].mean()) if not valid_hit.empty else np.nan
                            valid_alpha = valid_ret - base_valid_120 if pd.notna(valid_ret) and pd.notna(base_valid_120) else np.nan
                            valid_dd = float(valid_hit["max_dd_120d"].mean()) if not valid_hit.empty else np.nan
                            valid_eff = (valid_ret / abs(valid_dd)) if pd.notna(valid_ret) and pd.notna(valid_dd) and valid_dd != 0 else np.nan
                            rows.append(
                                {
                                    "fold": fold + 1,
                                    "min_close_above_p0_days": d,
                                    "min_ret_30d_from_p0": r,
                                    "max_atr_mean_pct": a,
                                    "min_vol_ratio_mean_30d": v,
                                    "min_max_drawdown_from_p0": dd,
                                    "valid_events": int(len(valid_hit)),
                                    "base_valid_ret120": base_valid_120,
                                    "valid_ret120": valid_ret,
                                    "valid_alpha120": valid_alpha,
                                    "valid_eff120": valid_eff,
                                    "valid_win120": float((valid_hit["ret_120d"] > 0).mean()) if not valid_hit.empty else np.nan,
                                }
                            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def summarize_extended_feature_stability(rolling_df: pd.DataFrame, min_valid_events: int = 5) -> pd.DataFrame:
    if rolling_df.empty:
        return pd.DataFrame()
    df = rolling_df.copy()
    df["is_effective_fold"] = (df["valid_events"] >= min_valid_events) & (df["valid_alpha120"] > 0)
    keys = [
        "min_close_above_p0_days",
        "min_ret_30d_from_p0",
        "max_atr_mean_pct",
        "min_vol_ratio_mean_30d",
        "min_max_drawdown_from_p0",
    ]
    out = df.groupby(keys, as_index=False).agg(
        folds=("fold", "count"),
        effective_folds=("is_effective_fold", "sum"),
        avg_valid_events=("valid_events", "mean"),
        avg_valid_alpha120=("valid_alpha120", "mean"),
        avg_valid_ret120=("valid_ret120", "mean"),
        avg_valid_eff120=("valid_eff120", "mean"),
        avg_valid_win120=("valid_win120", "mean"),
    )
    out["effective_ratio"] = out["effective_folds"] / out["folds"]
    out["stable_flag"] = out["effective_folds"] >= 2
    out = out.sort_values(
        ["stable_flag", "effective_folds", "avg_valid_eff120", "avg_valid_alpha120", "avg_valid_events"],
        ascending=[False, False, False, False, False],
    )
    return out


def _attach_soft_feature_scores(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return panel.copy()
    out = panel.copy()
    out["eval_date"] = pd.to_datetime(out["eval_date"])
    parts: List[pd.DataFrame] = []
    for _, g in out.groupby("eval_date"):
        gg = g.copy()
        atr_rank = 1.0 - pd.to_numeric(gg["atr_mean_pct"], errors="coerce").rank(pct=True, method="average")
        vol_rank = pd.to_numeric(gg["vol_ratio_mean_30d"], errors="coerce").rank(pct=True, method="average")
        dd_rank = pd.to_numeric(gg["max_drawdown_from_p0"], errors="coerce").rank(pct=True, method="average")
        gg["soft_daily_score"] = atr_rank.fillna(0.5) * 35.0 + vol_rank.fillna(0.5) * 20.0 + dd_rank.fillna(0.5) * 45.0
        gg["blended_score"] = pd.to_numeric(gg["total_score"], errors="coerce").fillna(0.0) + gg["soft_daily_score"] * 0.4
        parts.append(gg)
    return pd.concat(parts, ignore_index=True).sort_values(["eval_date", "blended_score"], ascending=[True, False])


def rolling_soft_layer_validation(
    panel: pd.DataFrame,
    folds: int = 3,
    min_train_dates: int = 6,
    min_valid_dates: int = 3,
    min_close_above_p0_days: int = 18,
    min_ret_30d_from_p0: float = 0.0,
    top_pcts: Iterable[float] = (0.2, 0.3, 0.4),
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    work = _attach_soft_feature_scores(panel)
    work = work[
        (work["ret_30d_from_p0"] > min_ret_30d_from_p0)
        & (work["close_above_p0_days"] >= min_close_above_p0_days)
    ].copy()
    if work.empty:
        return pd.DataFrame()
    dates = np.array(sorted(pd.to_datetime(work["eval_date"]).dropna().unique()))
    if len(dates) < (min_train_dates + min_valid_dates + folds):
        return pd.DataFrame()

    rows: List[Dict[str, object]] = []
    for fold in range(folds):
        train_end_idx = min_train_dates + fold * max(1, (len(dates) - min_train_dates - min_valid_dates) // max(folds - 1, 1))
        valid_end_idx = min(len(dates), train_end_idx + min_valid_dates)
        valid_dates = dates[train_end_idx:valid_end_idx]
        if len(valid_dates) < min_valid_dates:
            continue
        valid = work[work["eval_date"].isin(valid_dates)].copy()
        if valid.empty:
            continue
        base_valid_ret120 = float(valid["ret_120d"].mean())
        base_valid_dd120 = float(valid["max_dd_120d"].mean())
        for pct in top_pcts:
            picks: List[pd.DataFrame] = []
            for _, g in valid.groupby("eval_date"):
                k = max(1, int(np.ceil(len(g) * float(pct))))
                picks.append(g.sort_values("blended_score", ascending=False).head(k))
            hit = pd.concat(picks, ignore_index=True) if picks else pd.DataFrame()
            valid_ret = float(hit["ret_120d"].mean()) if not hit.empty else np.nan
            valid_dd = float(hit["max_dd_120d"].mean()) if not hit.empty else np.nan
            valid_alpha = valid_ret - base_valid_ret120 if pd.notna(valid_ret) else np.nan
            valid_eff = (valid_ret / abs(valid_dd)) if pd.notna(valid_ret) and pd.notna(valid_dd) and valid_dd != 0 else np.nan
            rows.append(
                {
                    "fold": fold + 1,
                    "top_pct": float(pct),
                    "valid_events": int(len(hit)),
                    "base_valid_ret120": base_valid_ret120,
                    "valid_ret120": valid_ret,
                    "valid_alpha120": valid_alpha,
                    "base_valid_dd120": base_valid_dd120,
                    "valid_dd120": valid_dd,
                    "valid_eff120": valid_eff,
                    "valid_win120": float((hit["ret_120d"] > 0).mean()) if not hit.empty else np.nan,
                }
            )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def summarize_soft_layer_stability(rolling_df: pd.DataFrame, min_valid_events: int = 5) -> pd.DataFrame:
    if rolling_df.empty:
        return pd.DataFrame()
    df = rolling_df.copy()
    df["is_effective_fold"] = (df["valid_events"] >= min_valid_events) & (df["valid_alpha120"] > 0)
    out = df.groupby(["top_pct"], as_index=False).agg(
        folds=("fold", "count"),
        effective_folds=("is_effective_fold", "sum"),
        avg_valid_events=("valid_events", "mean"),
        avg_valid_alpha120=("valid_alpha120", "mean"),
        avg_valid_ret120=("valid_ret120", "mean"),
        avg_valid_dd120=("valid_dd120", "mean"),
        avg_valid_eff120=("valid_eff120", "mean"),
        avg_valid_win120=("valid_win120", "mean"),
    )
    out["effective_ratio"] = out["effective_folds"] / out["folds"]
    out["stable_flag"] = out["effective_folds"] >= 2
    return out.sort_values(
        ["stable_flag", "effective_folds", "avg_valid_eff120", "avg_valid_alpha120"],
        ascending=[False, False, False, False],
    )


def write_report(
    out_dir: str,
    panel: pd.DataFrame,
    q_summary: pd.DataFrame,
    monthly_top: pd.DataFrame,
    monthly_top_gated: pd.DataFrame,
    min_close_above_p0_days: int,
    feature_diff: pd.DataFrame,
    rule: Dict[str, float],
    train_valid_summary: pd.DataFrame,
    rolling_summary: pd.DataFrame,
) -> None:
    meta = {
        "events": len(panel),
        "stocks": int(panel["ts_code"].nunique()) if not panel.empty else 0,
        "date_min": str(pd.to_datetime(panel["p0_date"]).min().date()) if not panel.empty else "",
        "date_max": str(pd.to_datetime(panel["p0_date"]).max().date()) if not panel.empty else "",
    }
    lines = [
        "# MA120事件评分分组验证报告",
        "",
        "## 样本信息",
        "",
        f"- 事件数: {meta['events']}",
        f"- 股票数: {meta['stocks']}",
        f"- 事件日期范围: {meta['date_min']} 至 {meta['date_max']}",
        "",
        "## 赢家特征（训练期 Top20% vs Bottom20%）",
        "",
        "```",
        feature_diff.to_string(index=False) if not feature_diff.empty else "无数据",
        "```",
        "",
        "## 自动提取候选规则",
        "",
        "```",
        str(rule),
        "```",
        "",
        "## 规则在训练/验证期表现",
        "",
        "```",
        train_valid_summary.to_string(index=False) if not train_valid_summary.empty else "无数据",
        "```",
        "",
        "## 滚动验证稳定性（3段）",
        "",
        "说明：`stable_flag=true` 表示该参数组合在 3 段里至少 2 段验证期为正alpha且样本数达标。",
        "",
        "```",
        rolling_summary.to_string(index=False) if not rolling_summary.empty else "无数据",
        "```",
        "",
        "## 评分分组汇总（Q1低分 -> Q5高分）",
        "",
        "```",
        q_summary.to_string(),
        "```",
        "",
        "## 月度Top组合（按评分前30/自定义）",
        "",
        "```",
        monthly_top.to_string(index=False) if not monthly_top.empty else "无数据",
        "```",
        "",
        f"## 月度Top组合（高分 + ret_30d_from_p0>0 + close_above_p0_days>={min_close_above_p0_days}）",
        "",
        "```",
        monthly_top_gated.to_string(index=False) if not monthly_top_gated.empty else "无数据",
        "```",
    ]
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def run(config: ValidationConfig) -> str:
    panel = build_event_panel(config)
    panel = apply_industry_cap(panel, config.industry_cap_per_month)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(config.output_dir, f"ma120_event_validation_{timestamp}")
    os.makedirs(out_dir, exist_ok=True)
    panel.to_csv(os.path.join(out_dir, "event_panel.csv"), index=False, encoding="utf-8-sig")
    q_summary = summarize_by_score_quantile(panel, config.quantiles, config.horizons)
    q_summary.to_csv(os.path.join(out_dir, "score_quantile_summary.csv"), encoding="utf-8-sig")
    monthly_top = summarize_monthly_top(panel, top_n=30, horizons=config.horizons)
    monthly_top.to_csv(os.path.join(out_dir, "monthly_top30_summary.csv"), index=False, encoding="utf-8-sig")
    monthly_top_gated = summarize_monthly_top_with_gate(
        panel, top_n=30, horizons=config.horizons, min_close_above_p0_days=config.min_close_above_p0_days
    )
    monthly_top_gated.to_csv(
        os.path.join(out_dir, "monthly_top30_gated_summary.csv"), index=False, encoding="utf-8-sig"
    )
    gate_grid = gate_grid_search(
        panel=panel,
        top_n=30,
        horizons=config.horizons,
        day_thresholds=[15, 18, 20],
        ret_thresholds=[0.0, 0.03],
    )
    gate_grid.to_csv(os.path.join(out_dir, "gate_grid_search_summary.csv"), index=False, encoding="utf-8-sig")

    train, valid = _split_train_valid_by_time(panel, config.train_ratio)
    feature_diff = _winner_loser_feature_diff(train)
    rule = _derive_candidate_rule(feature_diff) if not feature_diff.empty else {
        "min_ret_30d_from_p0": 0.0,
        "min_close_above_p0_days": 15,
        "min_break_pre120_high_count": 2,
        "max_drawdown_from_p0": -0.08,
    }
    train_hit = apply_candidate_rule(train, rule)
    valid_hit = apply_candidate_rule(valid, rule)
    baseline_train = summarize_slice("train_all", train, config.horizons)
    baseline_valid = summarize_slice("valid_all", valid, config.horizons)
    picked_train = summarize_slice("train_rule", train_hit, config.horizons)
    picked_valid = summarize_slice("valid_rule", valid_hit, config.horizons)
    train_valid_summary = pd.DataFrame([baseline_train, picked_train, baseline_valid, picked_valid])
    feature_diff.to_csv(os.path.join(out_dir, "winner_loser_feature_diff.csv"), index=False, encoding="utf-8-sig")
    train_valid_summary.to_csv(os.path.join(out_dir, "train_valid_rule_summary.csv"), index=False, encoding="utf-8-sig")

    rolling_df = rolling_gate_validation(
        panel=panel,
        horizons=config.horizons,
        day_thresholds=[15, 18, 20],
        ret_thresholds=[0.0, 0.03],
        folds=3,
    )
    rolling_df.to_csv(os.path.join(out_dir, "rolling_gate_validation.csv"), index=False, encoding="utf-8-sig")
    rolling_summary = summarize_rolling_stability(rolling_df, min_valid_events=5)
    rolling_summary.to_csv(os.path.join(out_dir, "rolling_gate_stability_summary.csv"), index=False, encoding="utf-8-sig")
    extended_rolling_df = rolling_extended_feature_validation(
        panel=panel,
        folds=3,
    )
    extended_rolling_df.to_csv(
        os.path.join(out_dir, "rolling_extended_feature_validation.csv"), index=False, encoding="utf-8-sig"
    )
    extended_rolling_summary = summarize_extended_feature_stability(extended_rolling_df, min_valid_events=5)
    extended_rolling_summary.to_csv(
        os.path.join(out_dir, "rolling_extended_feature_stability_summary.csv"), index=False, encoding="utf-8-sig"
    )
    soft_layer_roll = rolling_soft_layer_validation(
        panel=panel,
        folds=3,
        min_close_above_p0_days=config.min_close_above_p0_days,
        min_ret_30d_from_p0=0.0,
        top_pcts=(0.2, 0.3, 0.4),
    )
    soft_layer_roll.to_csv(
        os.path.join(out_dir, "rolling_soft_layer_validation.csv"), index=False, encoding="utf-8-sig"
    )
    soft_layer_summary = summarize_soft_layer_stability(soft_layer_roll, min_valid_events=5)
    soft_layer_summary.to_csv(
        os.path.join(out_dir, "rolling_soft_layer_stability_summary.csv"), index=False, encoding="utf-8-sig"
    )

    # Practical monthly backtest using the stable candidate from research:
    # obs_days tends to be selected externally (e.g., 20), here we apply chosen gate to panel.
    monthly_bt = _build_monthly_returns_from_top(
        panel=panel,
        top_n=30,
        min_close_above_p0_days=15,
        min_ret_30d_from_p0=0.0,
        horizon=120,
        cost_oneway=0.0015,
    )
    monthly_bt.to_csv(os.path.join(out_dir, "practical_monthly_backtest.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame([_perf_from_monthly(monthly_bt)]).to_csv(
        os.path.join(out_dir, "practical_monthly_backtest_perf.csv"), index=False, encoding="utf-8-sig"
    )
    non_overlap = run_non_overlap_backtest(
        panel=panel,
        top_n=30,
        min_close_above_p0_days=15,
        min_ret_30d_from_p0=0.0,
        horizon=120,
        cost_oneway=0.0015,
    )
    non_overlap.to_csv(os.path.join(out_dir, "practical_non_overlap_backtest.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame([perf_from_non_overlap(non_overlap)]).to_csv(
        os.path.join(out_dir, "practical_non_overlap_backtest_perf.csv"), index=False, encoding="utf-8-sig"
    )

    write_report(
        out_dir,
        panel,
        q_summary,
        monthly_top,
        monthly_top_gated,
        config.min_close_above_p0_days,
        feature_diff,
        rule,
        train_valid_summary,
        rolling_summary,
    )
    return out_dir


def run_obs_sweep(base_cfg: ValidationConfig, obs_windows: Iterable[int]) -> tuple[str, pd.DataFrame]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = os.path.join(base_cfg.output_dir, f"ma120_obs_sweep_{timestamp}")
    os.makedirs(root, exist_ok=True)
    rows: List[Dict[str, object]] = []
    for w in obs_windows:
        cfg = ValidationConfig(**{**base_cfg.__dict__, "obs_days": int(w)})
        out_dir = run(cfg)
        roll_path = os.path.join(out_dir, "rolling_gate_stability_summary.csv")
        if not os.path.exists(roll_path):
            continue
        roll = pd.read_csv(roll_path)
        if roll.empty:
            continue
        best = roll.iloc[0].to_dict()
        best["obs_days"] = w
        best["run_dir"] = out_dir
        rows.append(best)
    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(
            ["stable_flag", "effective_folds", "avg_valid_eff120", "avg_valid_alpha120"],
            ascending=[False, False, False, False],
        )
    summary.to_csv(os.path.join(root, "obs_sweep_summary.csv"), index=False, encoding="utf-8-sig")
    return root, summary


def _build_monthly_returns_from_top(
    panel: pd.DataFrame,
    top_n: int,
    min_close_above_p0_days: int,
    min_ret_30d_from_p0: float,
    horizon: int,
    cost_oneway: float,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    df = panel.copy()
    df["eval_month"] = pd.to_datetime(df["eval_date"]).dt.to_period("M").dt.to_timestamp("M")
    rows: List[Dict[str, object]] = []
    for m, g in df.groupby("eval_month"):
        gated = g[(g["close_above_p0_days"] >= min_close_above_p0_days) & (g["ret_30d_from_p0"] > min_ret_30d_from_p0)]
        if gated.empty:
            continue
        top = gated.sort_values("total_score", ascending=False).head(top_n)
        gross = float(top[f"ret_{horizon}d"].mean())
        # Approximate one round-trip cost.
        net = gross - 2 * cost_oneway
        rows.append({"month": m, "n": int(len(top)), "gross_ret": gross, "net_ret": net})
    out = pd.DataFrame(rows).sort_values("month")
    if out.empty:
        return out
    out["equity"] = (1 + out["net_ret"]).cumprod()
    out["drawdown"] = out["equity"] / out["equity"].cummax() - 1
    return out


def _perf_from_monthly(monthly: pd.DataFrame) -> Dict[str, float]:
    if monthly.empty:
        return {"months": 0}
    r = monthly["net_ret"]
    years = len(r) / 12
    total = float((1 + r).prod() - 1)
    cagr = float((1 + total) ** (1 / years) - 1) if years > 0 else np.nan
    vol = float(r.std(ddof=0) * np.sqrt(12))
    sharpe = float((r.mean() * 12) / vol) if vol > 0 else np.nan
    mdd = float(monthly["drawdown"].min())
    win = float((r > 0).mean())
    return {
        "months": int(len(r)),
        "total_return": total,
        "cagr": cagr,
        "annual_vol": vol,
        "sharpe_0rf": sharpe,
        "max_drawdown": mdd,
        "win_rate": win,
        "avg_holdings": float(monthly["n"].mean()),
    }


def run_non_overlap_backtest(
    panel: pd.DataFrame,
    top_n: int,
    min_close_above_p0_days: int,
    min_ret_30d_from_p0: float,
    horizon: int,
    cost_oneway: float,
) -> pd.DataFrame:
    """Sequential non-overlap backtest.

    We only open a new cohort after the previous cohort's horizon exit date.
    This avoids overlapping horizon returns and gives a conservative estimate.
    """
    if panel.empty:
        return pd.DataFrame()
    df = panel.copy()
    df["eval_month"] = pd.to_datetime(df["eval_date"]).dt.to_period("M").dt.to_timestamp("M")
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df[f"sell_date_{horizon}d"] = pd.to_datetime(df[f"sell_date_{horizon}d"])
    months = sorted(df["eval_month"].dropna().unique())
    rows: List[Dict[str, object]] = []
    capital = 1.0
    free_after = pd.Timestamp.min
    for month in months:
        mdf = df[df["eval_month"] == month]
        mdf = mdf[
            (mdf["close_above_p0_days"] >= min_close_above_p0_days)
            & (mdf["ret_30d_from_p0"] > min_ret_30d_from_p0)
        ]
        if mdf.empty:
            continue
        # Respect non-overlap by requiring this cohort entry after previous exit.
        mdf = mdf[mdf["buy_date"] > free_after]
        if mdf.empty:
            continue
        top = mdf.sort_values("total_score", ascending=False).head(top_n)
        gross = float(top[f"ret_{horizon}d"].mean())
        net = gross - 2 * cost_oneway
        entry = top["buy_date"].min()
        exit_date = top[f"sell_date_{horizon}d"].max()
        capital *= (1 + net)
        rows.append(
            {
                "eval_month": month,
                "entry_date": entry,
                "exit_date": exit_date,
                "n": int(len(top)),
                "gross_ret": gross,
                "net_ret": net,
                "equity": capital,
            }
        )
        free_after = exit_date
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["drawdown"] = out["equity"] / out["equity"].cummax() - 1
    return out


def perf_from_non_overlap(trades: pd.DataFrame) -> Dict[str, float]:
    if trades.empty:
        return {"trades": 0}
    start = pd.to_datetime(trades["entry_date"].min())
    end = pd.to_datetime(trades["exit_date"].max())
    days = max((end - start).days, 1)
    years = days / 365.25
    total = float(trades["equity"].iloc[-1] - 1)
    cagr = float((1 + total) ** (1 / years) - 1) if years > 0 else np.nan
    r = trades["net_ret"]
    vol = float(r.std(ddof=0) * np.sqrt(12))
    sharpe = float((r.mean() * 12) / vol) if vol > 0 else np.nan
    mdd = float(trades["drawdown"].min())
    return {
        "trades": int(len(trades)),
        "start_date": str(start.date()),
        "end_date": str(end.date()),
        "years": float(years),
        "total_return": total,
        "cagr": cagr,
        "annual_vol_est": vol,
        "sharpe_0rf_est": sharpe,
        "max_drawdown": mdd,
        "win_rate": float((r > 0).mean()),
        "avg_holdings": float(trades["n"].mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MA120 breakthrough event grouped validation.")
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--prefixes", nargs="+", default=["sh", "sz"])
    parser.add_argument("--obs-days", type=int, default=30)
    parser.add_argument("--pre-high-lookback", type=int, default=120)
    parser.add_argument("--cooldown-days", type=int, default=60)
    parser.add_argument("--horizons", nargs="+", type=int, default=[30, 60, 120])
    parser.add_argument("--min-rows-for-ma120", type=int, default=260)
    parser.add_argument("--quantiles", type=int, default=5)
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--ma-slope-lookback", type=int, default=20)
    parser.add_argument("--min-close-above-p0-days", type=int, default=18)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--industry-cap-per-month", type=int, default=None)
    parser.add_argument("--obs-sweep", nargs="+", type=int, default=None)
    parser.add_argument("--require-multi-tf-up", action="store_true")
    parser.add_argument("--multi-tf-bonus", type=float, default=8.0)
    args = parser.parse_args()
    cfg = ValidationConfig(
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        prefixes=tuple(args.prefixes),
        obs_days=args.obs_days,
        pre_high_lookback=args.pre_high_lookback,
        cooldown_days=args.cooldown_days,
        horizons=tuple(args.horizons),
        min_rows_for_ma120=args.min_rows_for_ma120,
        quantiles=args.quantiles,
        max_stocks=args.max_stocks,
        ma_slope_lookback=args.ma_slope_lookback,
        min_close_above_p0_days=args.min_close_above_p0_days,
        train_ratio=args.train_ratio,
        industry_cap_per_month=args.industry_cap_per_month,
        require_multi_tf_up=args.require_multi_tf_up,
        multi_tf_bonus=args.multi_tf_bonus,
    )
    if args.obs_sweep:
        root, summary = run_obs_sweep(cfg, args.obs_sweep)
        print(f"输出目录: {root}")
        if not summary.empty:
            print(summary.to_string(index=False))
    else:
        out_dir = run(cfg)
        print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
