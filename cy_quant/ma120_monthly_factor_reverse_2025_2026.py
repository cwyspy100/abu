#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reverse-engineer MA120 monthly ranking factors from 2025, validate in 2026.

Research goal:
1) Build a monthly A-share snapshot pool:
   - close > MA120
   - consecutive days above MA120 >= obs_days
   - streak breakthrough date >= 2025-01-01
2) On 2025 monthly cross-sections, infer which as-of factors correlate with
   stronger forward returns.
3) Validate on 2026 with a practical Top10 monthly portfolio:
   - screen at month-end
   - execute next trading day open
   - equal weight
   - close-based monthly rebalance
   - intramonth hard stop: low <= entry * (1 - stop_pct) => exit at stop line
   - stay in cash until next rebalance after stop.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd


A_PREFIXES = ("sh60", "sh68", "sz00", "sz30", "sz001", "bj")
TRAIN_START = pd.Timestamp("2025-01-01")
TRAIN_END = pd.Timestamp("2025-12-31")
VALID_START = pd.Timestamp("2026-01-01")
VALID_END = pd.Timestamp("2026-12-31")
FORWARD_HORIZONS = (20, 40, 60)


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def is_a_symbol(symbol: str) -> bool:
    s = symbol.lower()
    return s.startswith(A_PREFIXES)


def parse_date(raw: pd.Series) -> pd.Series:
    s = raw.astype(str)
    if s.str.fullmatch(r"\d{8}").mean() > 0.8:
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def latest_file_map(csv_dir: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for fp in glob.glob(os.path.join(csv_dir, "*")):
        if os.path.isdir(fp):
            continue
        sym = symbol_from_path(fp)
        if not is_a_symbol(sym):
            continue
        prev = out.get(sym)
        if prev is None or os.path.basename(fp) > os.path.basename(prev):
            out[sym] = fp
    return out


def load_kline(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    dcol = "date" if "date" in df.columns else ("Unnamed: 0" if "Unnamed: 0" in df.columns else None)
    if dcol is None or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["dt"] = parse_date(out[dcol])
    for c in ["open", "high", "low", "close", "volume"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    need = [c for c in ["dt", "open", "high", "low", "close", "volume"] if c in out.columns]
    out = out[need].dropna(subset=["dt", "close"]).sort_values("dt").drop_duplicates(subset=["dt"], keep="last")
    out = out.reset_index(drop=True)
    if "open" not in out.columns:
        out["open"] = out["close"]
    if "high" not in out.columns:
        out["high"] = out["close"]
    if "low" not in out.columns:
        out["low"] = out["close"]
    if "volume" not in out.columns:
        out["volume"] = np.nan
    return out


def add_indicators(k: pd.DataFrame) -> pd.DataFrame:
    out = k.copy()
    out["ma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["ma60"] = out["close"].rolling(60, min_periods=60).mean()
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    out["ma120_slope20"] = out["ma120"] / out["ma120"].shift(20) - 1.0
    out["ret1"] = out["close"].pct_change()
    out["ret5"] = out["close"] / out["close"].shift(5) - 1.0
    out["ret20"] = out["close"] / out["close"].shift(20) - 1.0
    out["ret60"] = out["close"] / out["close"].shift(60) - 1.0
    out["high60"] = out["close"].rolling(60, min_periods=20).max()
    out["high120"] = out["close"].rolling(120, min_periods=60).max()
    out["price_vs_ma120"] = out["close"] / out["ma120"] - 1.0
    out["dist_to_high60"] = out["close"] / out["high60"] - 1.0
    out["dist_to_high120"] = out["close"] / out["high120"] - 1.0

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr20"] = tr.rolling(20, min_periods=20).mean()
    out["atr60"] = tr.rolling(60, min_periods=60).mean()
    out["atr20_vs_atr60"] = out["atr20"] / out["atr60"]

    out["vol20"] = out["volume"].rolling(20, min_periods=20).mean()
    out["vol5"] = out["volume"].rolling(5, min_periods=5).mean()
    out["volume_ratio20"] = out["volume"] / out["vol20"]
    out["volume_ratio5_20"] = out["vol5"] / out["vol20"]

    out["above_ma120"] = out["close"] > out["ma120"]
    grp = (~out["above_ma120"]).cumsum()
    out["above_days"] = out["above_ma120"].groupby(grp).cumcount() + 1
    out.loc[~out["above_ma120"], "above_days"] = 0
    out["streak_start_date"] = out["dt"].where(out["above_ma120"]).groupby(grp).transform("first")

    up20 = out["ret1"].gt(0).rolling(20, min_periods=20).sum()
    down20 = out["ret1"].lt(0).rolling(20, min_periods=20).sum()
    out["up_down_diff20"] = up20 - down20
    out["up_ratio20"] = up20 / 20.0

    dd20 = out["close"] / out["close"].rolling(20, min_periods=20).max() - 1.0
    out["drawdown20"] = dd20
    out["volatility20"] = out["ret1"].rolling(20, min_periods=20).std()

    nh20_ref = out["close"].shift(1).rolling(20, min_periods=20).max()
    out["is_nh20"] = (out["close"] > nh20_ref).astype(float)
    out["nh20_count20"] = out["is_nh20"].rolling(20, min_periods=20).sum()

    out["bull_ma_stack"] = (
        (out["ma20"] > out["ma60"]) & (out["ma60"] > out["ma120"])
    ).astype(float)
    return out


def load_calendar(csv_dir: str) -> List[pd.Timestamp]:
    candidates = [
        os.path.join(csv_dir, "sh000001_19910101_21000101"),
        os.path.join(csv_dir, "sh000001_19910101_21000101.csv"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if path is None:
        latest = latest_file_map(csv_dir)
        path = latest.get("sh600000") or next(iter(latest.values()))
    k = load_kline(path)
    if k.empty:
        raise RuntimeError("failed to load market calendar")
    cal = k[(k["dt"] >= TRAIN_START) & (k["dt"] <= VALID_END)]["dt"].tolist()
    if not cal:
        raise RuntimeError("empty market calendar in train/valid range")
    return cal


def month_end_dates(calendar: Sequence[pd.Timestamp]) -> List[pd.Timestamp]:
    s = pd.Series(pd.to_datetime(calendar))
    df = pd.DataFrame({"dt": s})
    df["month"] = df["dt"].dt.to_period("M")
    return df.groupby("month", as_index=False).tail(1)["dt"].tolist()


def next_trade_map(calendar: Sequence[pd.Timestamp]) -> Dict[pd.Timestamp, pd.Timestamp]:
    out: Dict[pd.Timestamp, pd.Timestamp] = {}
    for i, dt in enumerate(calendar[:-1]):
        out[pd.Timestamp(dt)] = pd.Timestamp(calendar[i + 1])
    return out


def future_close_return(k: pd.DataFrame, eval_idx: int, horizon: int) -> float:
    entry_idx = eval_idx + 1
    exit_idx = entry_idx + horizon - 1
    if exit_idx >= len(k):
        return np.nan
    entry_open = float(k.at[entry_idx, "open"])
    exit_close = float(k.at[exit_idx, "close"])
    if entry_open <= 0:
        return np.nan
    return exit_close / entry_open - 1.0


def build_snapshot_rows(
    symbol: str,
    k: pd.DataFrame,
    eval_dates: Sequence[pd.Timestamp],
) -> List[Dict[str, object]]:
    if len(k) < 180:
        return []
    rows: List[Dict[str, object]] = []
    dts = k["dt"].to_numpy()
    eval_pos = np.searchsorted(dts, np.array(eval_dates, dtype="datetime64[ns]"), side="right") - 1
    for eval_dt, idx in zip(eval_dates, eval_pos):
        if idx < 120 or idx >= len(k) - 61:
            continue
        r = k.iloc[int(idx)]
        if not bool(r["above_ma120"]):
            continue
        bt_date = pd.Timestamp(r["streak_start_date"]) if pd.notna(r["streak_start_date"]) else pd.NaT
        if pd.isna(bt_date) or bt_date < TRAIN_START:
            continue
        if any(pd.isna(r.get(c)) for c in ["ma120", "ma120_slope20", "ret20", "ret60"]):
            continue
        rows.append(
            {
                "symbol": symbol,
                "eval_date": pd.Timestamp(eval_dt),
                "breakthrough_date": bt_date,
                "above_days": int(r["above_days"]),
                "close": float(r["close"]),
                "open_next": float(k.at[int(idx) + 1, "open"]) if int(idx) + 1 < len(k) else np.nan,
                "price_vs_ma120": float(r["price_vs_ma120"]),
                "ma120_slope20": float(r["ma120_slope20"]),
                "ret5": float(r["ret5"]) if pd.notna(r["ret5"]) else np.nan,
                "ret20": float(r["ret20"]),
                "ret60": float(r["ret60"]),
                "dist_to_high60": float(r["dist_to_high60"]) if pd.notna(r["dist_to_high60"]) else np.nan,
                "dist_to_high120": float(r["dist_to_high120"]) if pd.notna(r["dist_to_high120"]) else np.nan,
                "volume_ratio20": float(r["volume_ratio20"]) if pd.notna(r["volume_ratio20"]) else np.nan,
                "volume_ratio5_20": float(r["volume_ratio5_20"]) if pd.notna(r["volume_ratio5_20"]) else np.nan,
                "atr20_vs_atr60": float(r["atr20_vs_atr60"]) if pd.notna(r["atr20_vs_atr60"]) else np.nan,
                "up_down_diff20": float(r["up_down_diff20"]) if pd.notna(r["up_down_diff20"]) else np.nan,
                "up_ratio20": float(r["up_ratio20"]) if pd.notna(r["up_ratio20"]) else np.nan,
                "drawdown20": float(r["drawdown20"]) if pd.notna(r["drawdown20"]) else np.nan,
                "volatility20": float(r["volatility20"]) if pd.notna(r["volatility20"]) else np.nan,
                "nh20_count20": float(r["nh20_count20"]) if pd.notna(r["nh20_count20"]) else np.nan,
                "bull_ma_stack": float(r["bull_ma_stack"]),
                "ret_fwd_20d": future_close_return(k, int(idx), 20),
                "ret_fwd_40d": future_close_return(k, int(idx), 40),
                "ret_fwd_60d": future_close_return(k, int(idx), 60),
            }
        )
    return rows


def build_snapshot_panel(csv_dir: str, output_dir: str) -> str:
    calendar = load_calendar(csv_dir)
    eval_dates = month_end_dates(calendar)
    files = latest_file_map(csv_dir)
    all_rows: List[Dict[str, object]] = []
    loaded = 0
    for symbol, path in sorted(files.items()):
        k = add_indicators(load_kline(path))
        if k.empty:
            continue
        loaded += 1
        all_rows.extend(build_snapshot_rows(symbol, k, eval_dates))
        if loaded % 500 == 0:
            print(f"loaded {loaded}/{len(files)} symbols...")
    panel = pd.DataFrame(all_rows)
    if panel.empty:
        raise RuntimeError("empty monthly snapshot panel")
    panel["year"] = pd.to_datetime(panel["eval_date"]).dt.year
    panel["eval_month"] = pd.to_datetime(panel["eval_date"]).dt.to_period("M").astype(str)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_monthly_factor_reverse_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    panel.to_csv(os.path.join(out_dir, "monthly_snapshot_panel.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame({"eval_date": eval_dates}).to_csv(
        os.path.join(out_dir, "eval_dates.csv"), index=False, encoding="utf-8-sig"
    )
    print(out_dir)
    print(panel.groupby("year")["symbol"].count().rename("rows").to_string())
    return out_dir


def rank_ic(sub: pd.DataFrame, feature: str, label: str) -> float:
    x = pd.to_numeric(sub[feature], errors="coerce")
    y = pd.to_numeric(sub[label], errors="coerce")
    mask = x.notna() & y.notna()
    if int(mask.sum()) < 8:
        return np.nan
    xr = x[mask].rank(pct=True)
    yr = y[mask].rank(pct=True)
    return float(xr.corr(yr))


def feature_ic_table(train: pd.DataFrame, features: Sequence[str]) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for feat in features:
        all_ics: List[float] = []
        row: Dict[str, object] = {"feature": feat}
        for h in FORWARD_HORIZONS:
            label = f"ret_fwd_{h}d"
            by_month = []
            for _, sub in train.groupby("eval_month"):
                ic = rank_ic(sub, feat, label)
                if pd.notna(ic):
                    by_month.append(ic)
            row[f"ic_mean_{h}d"] = float(np.mean(by_month)) if by_month else np.nan
            row[f"ic_pos_ratio_{h}d"] = float(np.mean(np.array(by_month) > 0)) if by_month else np.nan
            all_ics.extend([x for x in by_month if pd.notna(x)])
        sign_score = np.nanmean([row[f"ic_mean_{h}d"] for h in FORWARD_HORIZONS])
        row["sign"] = 1.0 if sign_score >= 0 else -1.0
        row["abs_ic_mean"] = float(
            np.nanmean([abs(row[f"ic_mean_{h}d"]) for h in FORWARD_HORIZONS])
        )
        row["stable_horizons"] = int(
            sum(
                (
                    pd.notna(row[f"ic_mean_{h}d"])
                    and abs(row[f"ic_mean_{h}d"]) >= 0.02
                    and (
                        (row["sign"] > 0 and row[f"ic_pos_ratio_{h}d"] >= 0.50)
                        or (row["sign"] < 0 and row[f"ic_pos_ratio_{h}d"] <= 0.50)
                    )
                )
                for h in FORWARD_HORIZONS
            )
        )
        row["overall_score"] = row["abs_ic_mean"] * max(row["stable_horizons"], 0)
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values(["overall_score", "abs_ic_mean"], ascending=[False, False]).reset_index(drop=True)


def pct_rank(series: pd.Series, ascending: bool) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rank(pct=True, ascending=ascending)


def apply_score(df: pd.DataFrame, specs: Sequence[Tuple[str, float]]) -> pd.Series:
    parts = []
    for feat, sign in specs:
        parts.append(pct_rank(df[feat], ascending=(sign < 0)))
    if not parts:
        return pd.Series(np.nan, index=df.index)
    return pd.concat(parts, axis=1).mean(axis=1)


def choose_combos(ic_df: pd.DataFrame, top_k: int = 5) -> List[Tuple[str, Tuple[str, ...], List[Tuple[str, float]]]]:
    top = ic_df.head(top_k).copy()
    signed = [(str(r["feature"]), float(r["sign"])) for _, r in top.iterrows()]
    combos: List[Tuple[str, Tuple[str, ...], List[Tuple[str, float]]]] = []
    if signed:
        combos.append(("best_single", (signed[0][0],), [signed[0]]))
    if len(signed) >= 3:
        top3 = signed[:3]
        combos.append(("top3_combo", tuple(f for f, _ in top3), top3))
    if len(signed) >= 5:
        top5 = signed[:5]
        combos.append(("top5_combo", tuple(f for f, _ in top5), top5))
    return combos


def build_ranked_panel(panel: pd.DataFrame, obs_days: int, score_spec: Sequence[Tuple[str, float]]) -> pd.DataFrame:
    sub = panel[panel["above_days"] >= obs_days].copy()
    if sub.empty:
        return sub
    rank_cols = []
    for feat, sign in score_spec:
        col = f"_rank_{feat}"
        sub[col] = sub.groupby("eval_month")[feat].rank(pct=True, ascending=(sign < 0))
        rank_cols.append(col)
    sub["score"] = sub[rank_cols].mean(axis=1)
    sub = sub.drop(columns=rank_cols)
    sub["rank_in_month"] = sub.groupby("eval_month")["score"].rank(method="first", ascending=False)
    return sub.sort_values(["eval_date", "rank_in_month", "symbol"]).reset_index(drop=True)


def _perf_summary(daily: pd.DataFrame, trades: pd.DataFrame) -> Dict[str, object]:
    eq = daily["equity"].astype(float)
    total = float(eq.iloc[-1] - 1.0) if len(eq) else np.nan
    years = max((pd.Timestamp(daily["date"].iloc[-1]) - pd.Timestamp(daily["date"].iloc[0])).days / 365.25, 1e-9) if len(daily) else np.nan
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if len(eq) and eq.iloc[-1] > 0 else np.nan
    dd = eq / eq.cummax() - 1.0 if len(eq) else pd.Series(dtype=float)
    daily_ret = eq.pct_change().fillna(0.0) if len(eq) else pd.Series(dtype=float)
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if len(eq) and daily_ret.std() > 0 else np.nan
    return {
        "days": int(len(daily)),
        "start": str(pd.Timestamp(daily["date"].min()).date()) if len(daily) else "",
        "end": str(pd.Timestamp(daily["date"].max()).date()) if len(daily) else "",
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": float(dd.min()) if len(dd) else np.nan,
        "sharpe": sharpe,
        "trades": int(len(trades)),
        "win_rate": float((trades["ret"] > 0).mean()) if len(trades) else np.nan,
        "avg_trade_ret": float(trades["ret"].mean()) if len(trades) else np.nan,
        "median_trade_ret": float(trades["ret"].median()) if len(trades) else np.nan,
        "avg_active": float(daily["active_n"].mean()) if len(daily) else np.nan,
        "avg_exposure": float(daily["exposure"].mean()) if len(daily) else np.nan,
    }


def simulate_top10(
    ranked: pd.DataFrame,
    csv_dir: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    stop_pct: float,
    cost_oneway: float,
    price_cache: Dict[str, pd.DataFrame],
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    files = latest_file_map(csv_dir)
    calendar = [d for d in load_calendar(csv_dir) if start <= d <= end]
    next_map = next_trade_map(calendar)

    panel = ranked[(pd.to_datetime(ranked["eval_date"]) >= start) & (pd.to_datetime(ranked["eval_date"]) <= end)].copy()
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    by_eval = {d: g.sort_values("rank_in_month") for d, g in panel.groupby("eval_date")}

    rebalance_dates = [next_map[d] for d in sorted(by_eval.keys()) if d in next_map and next_map[d] <= end]
    picks_by_rebalance = {
        next_map[d]: by_eval[d].head(top_n).copy()
        for d in sorted(by_eval.keys())
        if d in next_map and next_map[d] <= end
    }

    positions: Dict[str, Dict[str, object]] = {}
    closed: List[Dict[str, object]] = []
    daily_rows: List[Dict[str, object]] = []
    equity = 1.0

    for date in calendar:
        day_ret = 0.0
        forced_closes: List[Tuple[str, float, str]] = []

        for code, pos in list(positions.items()):
            if code not in files:
                continue
            if code not in price_cache:
                base = load_kline(files[code])[["dt", "open", "low", "close"]].dropna().drop_duplicates(subset=["dt"], keep="last")
                price_cache[code] = base.set_index("dt").sort_index()
            k = price_cache[code]
            if date not in k.index:
                continue
            row = k.loc[date]
            last_price = float(pos["last_price"])
            close_px = float(row["close"]) if isinstance(row, pd.Series) else float(row.iloc[-1]["close"])
            day_ret += float(pos["weight"]) * (close_px / last_price - 1.0)
            stop_line = float(pos["entry_price"]) * (1.0 - stop_pct)
            low_px = float(row["low"]) if isinstance(row, pd.Series) else float(row.iloc[-1]["low"])
            if low_px <= stop_line:
                forced_closes.append((code, stop_line, "stop10"))
            pos["last_price"] = close_px

        if date in rebalance_dates:
            for code, pos in list(positions.items()):
                if code not in files:
                    continue
                if code not in price_cache:
                    base = load_kline(files[code])[["dt", "open", "low", "close"]].dropna().drop_duplicates(subset=["dt"], keep="last")
                    price_cache[code] = base.set_index("dt").sort_index()
                k = price_cache[code]
                if date not in k.index:
                    continue
                row = k.loc[date]
                open_px = float(row["open"]) if isinstance(row, pd.Series) else float(row.iloc[-1]["open"])
                day_ret += float(pos["weight"]) * (open_px / float(pos["last_price"]) - 1.0)
                day_ret -= cost_oneway * float(pos["weight"])
                closed.append(
                    {
                        "symbol": code,
                        "entry_date": pos["entry_date"],
                        "exit_date": date,
                        "entry_price": pos["entry_price"],
                        "exit_price": open_px,
                        "ret": open_px / float(pos["entry_price"]) - 1.0,
                        "reason": "rebalance",
                    }
                )
                positions.pop(code, None)

            picks = picks_by_rebalance.get(date)
            if picks is not None and len(picks):
                weight = 1.0 / float(top_n)
                for _, r in picks.iterrows():
                    code = str(r["symbol"])
                    if code not in files:
                        continue
                    if code not in price_cache:
                        base = load_kline(files[code])[["dt", "open", "low", "close"]].dropna().drop_duplicates(subset=["dt"], keep="last")
                        price_cache[code] = base.set_index("dt").sort_index()
                    k = price_cache[code]
                    if date not in k.index:
                        continue
                    row = k.loc[date]
                    open_px = float(row["open"]) if isinstance(row, pd.Series) else float(row.iloc[-1]["open"])
                    positions[code] = {
                        "entry_date": date,
                        "entry_price": open_px,
                        "last_price": open_px,
                        "weight": weight,
                    }
                    day_ret -= cost_oneway * weight

        for code, exit_px, reason in forced_closes:
            pos = positions.pop(code, None)
            if pos is None:
                continue
            current_close = float(pos["last_price"])
            day_ret += float(pos["weight"]) * (exit_px / current_close - 1.0)
            day_ret -= cost_oneway * float(pos["weight"])
            closed.append(
                {
                    "symbol": code,
                    "entry_date": pos["entry_date"],
                    "exit_date": date,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_px,
                    "ret": exit_px / float(pos["entry_price"]) - 1.0,
                    "reason": reason,
                }
            )

        equity *= 1.0 + day_ret
        daily_rows.append(
            {
                "date": date,
                "equity": equity,
                "active_n": len(positions),
                "exposure": sum(float(p["weight"]) for p in positions.values()),
            }
        )

    daily = pd.DataFrame(daily_rows)
    trades = pd.DataFrame(closed)
    return daily, trades, _perf_summary(daily, trades)


def run_research(panel_csv: str, csv_dir: str, output_dir: str, top_n: int, stop_pct: float, cost_bps: float) -> str:
    panel = pd.read_csv(panel_csv)
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    panel["breakthrough_date"] = pd.to_datetime(panel["breakthrough_date"])
    feature_cols = [
        "above_days",
        "price_vs_ma120",
        "ma120_slope20",
        "ret5",
        "ret20",
        "ret60",
        "dist_to_high60",
        "dist_to_high120",
        "volume_ratio20",
        "volume_ratio5_20",
        "atr20_vs_atr60",
        "up_down_diff20",
        "up_ratio20",
        "drawdown20",
        "volatility20",
        "nh20_count20",
        "bull_ma_stack",
    ]

    train = panel[(panel["eval_date"] >= TRAIN_START) & (panel["eval_date"] <= TRAIN_END)].copy()
    valid = panel[(panel["eval_date"] >= VALID_START) & (panel["eval_date"] <= VALID_END)].copy()
    if train.empty or valid.empty:
        raise RuntimeError("train/valid panel empty")

    cost_oneway = cost_bps / 10000.0
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_monthly_factor_research_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    price_cache: Dict[str, pd.DataFrame] = {}

    ic_rows: List[pd.DataFrame] = []
    combo_rows: List[Dict[str, object]] = []
    daily_exports: List[Tuple[str, pd.DataFrame]] = []
    trade_exports: List[Tuple[str, pd.DataFrame]] = []

    for obs_days in [10, 20, 30, 40, 50, 60]:
        train_obs = train[train["above_days"] >= obs_days].copy()
        valid_obs = valid[valid["above_days"] >= obs_days].copy()
        if len(train_obs) < 100 or len(valid_obs) < 50:
            continue
        ic_df = feature_ic_table(train_obs, feature_cols)
        ic_df["obs_days"] = obs_days
        ic_rows.append(ic_df)

        for combo_name, feats, signed in choose_combos(ic_df):
            ranked = build_ranked_panel(panel, obs_days, signed)
            daily_2025, trades_2025, perf_2025 = simulate_top10(
                ranked, csv_dir, TRAIN_START, TRAIN_END, top_n, stop_pct, cost_oneway, price_cache
            )
            daily_2026, trades_2026, perf_2026 = simulate_top10(
                ranked, csv_dir, VALID_START, VALID_END, top_n, stop_pct, cost_oneway, price_cache
            )
            row = {
                "obs_days": obs_days,
                "combo_name": combo_name,
                "features": ",".join(feats),
                "train_total_return": perf_2025["total_return"],
                "train_cagr": perf_2025["cagr"],
                "train_max_drawdown": perf_2025["max_drawdown"],
                "train_sharpe": perf_2025["sharpe"],
                "valid_total_return": perf_2026["total_return"],
                "valid_cagr": perf_2026["cagr"],
                "valid_max_drawdown": perf_2026["max_drawdown"],
                "valid_sharpe": perf_2026["sharpe"],
                "valid_trades": perf_2026["trades"],
                "valid_win_rate": perf_2026["win_rate"],
                "valid_avg_trade_ret": perf_2026["avg_trade_ret"],
                "valid_avg_active": perf_2026["avg_active"],
                "valid_avg_exposure": perf_2026["avg_exposure"],
            }
            combo_rows.append(row)
            label = f"obs{obs_days}_{combo_name}"
            daily_exports.append((f"{label}_daily_2026.csv", daily_2026))
            trade_exports.append((f"{label}_trades_2026.csv", trades_2026))

    ic_table = pd.concat(ic_rows, ignore_index=True) if ic_rows else pd.DataFrame()
    combo_table = pd.DataFrame(combo_rows)
    if combo_table.empty:
        raise RuntimeError("no valid obs_days / combo results")

    combo_table["valid_score"] = combo_table["valid_cagr"] + combo_table["valid_max_drawdown"] * 0.5
    combo_table = combo_table.sort_values(
        ["valid_cagr", "valid_max_drawdown", "valid_sharpe"], ascending=[False, False, False]
    ).reset_index(drop=True)

    ic_table.to_csv(os.path.join(out_dir, "train_feature_ic_summary.csv"), index=False, encoding="utf-8-sig")
    combo_table.to_csv(os.path.join(out_dir, "combo_validation_summary.csv"), index=False, encoding="utf-8-sig")
    for name, df in daily_exports[:6]:
        df.to_csv(os.path.join(out_dir, name), index=False, encoding="utf-8-sig")
    for name, df in trade_exports[:6]:
        df.to_csv(os.path.join(out_dir, name), index=False, encoding="utf-8-sig")

    report_lines = [
        "# MA120 Monthly Factor Reverse Research",
        "",
        "## Setup",
        "",
        f"- Train: `2025-01-01` to `2025-12-31`",
        f"- Valid: `2026-01-01` to `2026-12-31`",
        f"- Monthly screen: month-end close",
        f"- Execution: next trading day open",
        f"- Portfolio: `Top {top_n}` equal-weight",
        f"- Stop: `{stop_pct:.0%}` intramonth hard stop via daily low",
        f"- Cost: `{cost_bps} bps` one-way",
        "",
        "## Best Validation Results",
        "",
        combo_table.head(10)[
            [
                "obs_days",
                "combo_name",
                "features",
                "train_cagr",
                "train_max_drawdown",
                "valid_cagr",
                "valid_max_drawdown",
                "valid_sharpe",
                "valid_trades",
            ]
        ].to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "research_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(out_dir)
    print(combo_table.head(10).to_string(index=False))
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse-engineer monthly MA120 ranking factors from 2025, validate on 2026.")
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--panel-csv", default="")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--stop-pct", type=float, default=0.10)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()

    if args.panel_csv:
        panel_csv = args.panel_csv
    else:
        panel_root = build_snapshot_panel(args.csv_dir, args.output_dir)
        panel_csv = os.path.join(panel_root, "monthly_snapshot_panel.csv")
    run_research(panel_csv, args.csv_dir, args.output_dir, args.top_n, args.stop_pct, args.cost_bps)


if __name__ == "__main__":
    main()
