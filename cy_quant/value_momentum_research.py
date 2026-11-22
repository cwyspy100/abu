"""Value and momentum factor validation on local Tushare caches.

The first goal of this module is research hygiene: build a small, repeatable
cross-sectional test before turning factors into a production stock picker.
"""

from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class ResearchConfig:
    cache_dir: str = os.path.expanduser("~/abu/tushare")
    kline_dir: Optional[str] = None
    output_dir: str = "cy_quant/output"
    min_price_months: int = 14
    quantiles: int = 5
    top_n: int = 30
    min_stocks_per_month: int = 20
    max_stocks: Optional[int] = None


def _parse_yyyymmdd(value) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    text = str(value).split(".")[0]
    return pd.to_datetime(text, format="%Y%m%d", errors="coerce")


def _ts_code_from_daily_path(path: str) -> Optional[str]:
    base = os.path.basename(path)
    parts = base.split("_")
    if len(parts) < 2:
        return None
    code, market = parts[0], parts[1]
    if len(code) != 6 or market not in {"SH", "SZ", "BJ"}:
        return None
    return f"{code}.{market}"


def _ts_code_from_abu_csv_path(path: str) -> Optional[str]:
    base = os.path.basename(path)
    prefix = base.split("_")[0]
    if len(prefix) != 8:
        return None
    market, code = prefix[:2], prefix[2:]
    if not code.isdigit():
        return None
    market_map = {"sh": "SH", "sz": "SZ", "bj": "BJ"}
    if market not in market_map:
        return None
    return f"{code}.{market_map[market]}"


def _daily_path_for_ts_code(cache_dir: str, ts_code: str) -> Optional[str]:
    code, market = ts_code.split(".")
    pattern = os.path.join(cache_dir, "daily", f"{code}_{market}_daily_*.csv")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def _abu_csv_path_for_ts_code(kline_dir: str, ts_code: str) -> Optional[str]:
    code, market = ts_code.split(".")
    prefix_map = {"SH": "sh", "SZ": "sz", "BJ": "bj"}
    prefix = prefix_map.get(market)
    if prefix is None:
        return None
    pattern = os.path.join(kline_dir, f"{prefix}{code}_*")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def _finance_path_for_ts_code(cache_dir: str, ts_code: str) -> Optional[str]:
    code, market = ts_code.split(".")
    path = os.path.join(cache_dir, "finance", f"{code}_{market}_finance.csv")
    return path if os.path.exists(path) else None


def discover_local_universe(cache_dir: str, kline_dir: Optional[str] = None) -> List[str]:
    """Return stocks that have both daily and finance cache files."""
    if kline_dir:
        daily_paths = glob.glob(os.path.join(kline_dir, "*"))
        daily_codes = {_ts_code_from_abu_csv_path(path) for path in daily_paths}
    else:
        daily_paths = glob.glob(os.path.join(cache_dir, "daily", "*_daily_*.csv"))
        daily_codes = {_ts_code_from_daily_path(path) for path in daily_paths}
    daily_codes.discard(None)
    universe = [
        ts_code
        for ts_code in sorted(daily_codes)
        if _finance_path_for_ts_code(cache_dir, ts_code) is not None
    ]
    return universe


def load_stock_basic(cache_dir: str) -> pd.DataFrame:
    candidates = [
        os.path.join(cache_dir, "finance", "stock_basic_all.csv"),
        os.path.join(cache_dir, "stock_list", "stock_basic_list_20260329.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return pd.read_csv(path)
    return pd.DataFrame(columns=["ts_code", "name", "industry"])


def load_daily_monthly(cache_dir: str, ts_code: str, kline_dir: Optional[str] = None) -> pd.DataFrame:
    path = _abu_csv_path_for_ts_code(kline_dir, ts_code) if kline_dir else _daily_path_for_ts_code(cache_dir, ts_code)
    if path is None:
        return pd.DataFrame()
    df = pd.read_csv(path, usecols=lambda col: col in {"trade_date", "date", "close"})
    if "trade_date" not in df.columns and "date" in df.columns:
        df = df.rename(columns={"date": "trade_date"})
    if "trade_date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df[["trade_date", "close"]].copy()
    out["trade_date"] = out["trade_date"].apply(_parse_yyyymmdd)
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
    out["month"] = out["trade_date"].dt.to_period("M").dt.to_timestamp("M")
    monthly = out.groupby("month", as_index=False).tail(1)
    return monthly[["month", "close"]].assign(ts_code=ts_code)


def load_finance_asof_rows(cache_dir: str, ts_code: str) -> pd.DataFrame:
    path = _finance_path_for_ts_code(cache_dir, ts_code)
    if path is None:
        return pd.DataFrame()
    needed = {"ts_code", "end_date", "eps", "bps", "roe", "n_income", "ann_date_x", "ann_date_y", "f_ann_date", "ann_date"}
    df = pd.read_csv(path, usecols=lambda col: col in needed)
    ann_candidates = [c for c in ["ann_date_x", "ann_date_y", "f_ann_date", "ann_date"] if c in df.columns]
    if not ann_candidates:
        return pd.DataFrame()
    ann = pd.Series(pd.NaT, index=df.index)
    for col in ann_candidates:
        ann = ann.fillna(df[col].apply(_parse_yyyymmdd))
    keep_cols = [c for c in ["ts_code", "end_date", "eps", "bps", "roe", "n_income"] if c in df.columns]
    out = df[keep_cols].copy()
    out["ann_date"] = ann
    out["eps"] = pd.to_numeric(out.get("eps"), errors="coerce")
    out["bps"] = pd.to_numeric(out.get("bps"), errors="coerce")
    out["roe"] = pd.to_numeric(out.get("roe"), errors="coerce")
    out["n_income"] = pd.to_numeric(out.get("n_income"), errors="coerce")
    out = out.dropna(subset=["ann_date"]).sort_values("ann_date")
    return out


def build_monthly_price_panel(cache_dir: str, universe: Iterable[str]) -> pd.DataFrame:
    frames = [load_daily_monthly(cache_dir, ts_code) for ts_code in universe]
    frames = [df for df in frames if not df.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_monthly_price_panel_from_config(config: ResearchConfig, universe: Iterable[str]) -> pd.DataFrame:
    frames = [load_daily_monthly(config.cache_dir, ts_code, config.kline_dir) for ts_code in universe]
    frames = [df for df in frames if not df.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _latest_finance_before(finance: pd.DataFrame, asof: pd.Timestamp) -> Optional[pd.Series]:
    eligible = finance[finance["ann_date"] <= asof]
    if eligible.empty:
        return None
    return eligible.iloc[-1]


def build_factor_panel(config: ResearchConfig, universe: Optional[List[str]] = None) -> pd.DataFrame:
    """Build monthly factor observations and next-month returns."""
    if universe is None:
        universe = discover_local_universe(config.cache_dir, config.kline_dir)
    prices = build_monthly_price_panel_from_config(config, universe)
    if prices.empty:
        return pd.DataFrame()

    wide_close = prices.pivot(index="month", columns="ts_code", values="close").sort_index()
    enough_history = wide_close.count()
    valid_codes = enough_history[enough_history >= config.min_price_months].index.tolist()
    wide_close = wide_close[valid_codes]
    universe = [ts_code for ts_code in universe if ts_code in valid_codes]
    forward_ret = wide_close.shift(-1) / wide_close - 1
    mom_3m = wide_close / wide_close.shift(3) - 1
    mom_6m = wide_close / wide_close.shift(6) - 1
    mom_12_1 = wide_close.shift(1) / wide_close.shift(12) - 1
    finance_by_code = {ts_code: load_finance_asof_rows(config.cache_dir, ts_code) for ts_code in universe}

    rows: List[Dict[str, object]] = []
    for month in wide_close.index:
        for ts_code in universe:
            price = wide_close.at[month, ts_code] if ts_code in wide_close.columns else np.nan
            next_ret = forward_ret.at[month, ts_code] if ts_code in forward_ret.columns else np.nan
            if pd.isna(price) or pd.isna(next_ret):
                continue
            finance = finance_by_code.get(ts_code, pd.DataFrame())
            latest = _latest_finance_before(finance, month) if not finance.empty else None
            if latest is None:
                continue
            eps = latest.get("eps", np.nan)
            bps = latest.get("bps", np.nan)
            roe = latest.get("roe", np.nan)
            n_income = latest.get("n_income", np.nan)
            rows.append(
                {
                    "month": month,
                    "ts_code": ts_code,
                    "close": price,
                    "forward_1m_return": next_ret,
                    "earnings_yield": eps / price if pd.notna(eps) and price > 0 else np.nan,
                    "book_to_price": bps / price if pd.notna(bps) and price > 0 else np.nan,
                    "roe": roe,
                    "n_income": n_income,
                    "momentum_3m": mom_3m.at[month, ts_code] if ts_code in mom_3m.columns else np.nan,
                    "momentum_6m": mom_6m.at[month, ts_code] if ts_code in mom_6m.columns else np.nan,
                    "momentum_12_1": mom_12_1.at[month, ts_code] if ts_code in mom_12_1.columns else np.nan,
                    "finance_ann_date": latest.get("ann_date"),
                    "finance_end_date": latest.get("end_date"),
                }
            )
    panel = pd.DataFrame(rows)
    if panel.empty:
        return panel
    panel = panel.groupby("month").filter(lambda x: len(x) >= config.min_stocks_per_month)
    return add_factor_scores(panel)


def add_factor_scores(panel: pd.DataFrame) -> pd.DataFrame:
    """Add cross-sectional value, momentum, and composite percentile scores."""
    out = panel.copy()
    grouped = out.groupby("month", group_keys=False)
    out["earnings_yield_rank"] = grouped["earnings_yield"].rank(pct=True)
    out["book_to_price_rank"] = grouped["book_to_price"].rank(pct=True)
    out["momentum_3m_rank"] = grouped["momentum_3m"].rank(pct=True)
    out["momentum_6m_rank"] = grouped["momentum_6m"].rank(pct=True)
    out["momentum_12_1_rank"] = grouped["momentum_12_1"].rank(pct=True)
    out["quality_pass"] = (out["roe"].fillna(-999) > 0) & (out["n_income"].fillna(-1) > 0)
    out["value_score"] = out[["earnings_yield_rank", "book_to_price_rank"]].mean(axis=1)
    out["momentum_score"] = out[["momentum_6m_rank", "momentum_12_1_rank"]].mean(axis=1)
    out["short_momentum_score"] = out[["momentum_3m_rank", "momentum_6m_rank"]].mean(axis=1)
    out["composite_score"] = out[["value_score", "momentum_score"]].mean(axis=1)
    out.loc[~out["quality_pass"], "value_score"] *= 0.5
    out.loc[~out["quality_pass"], "composite_score"] = out.loc[
        ~out["quality_pass"], ["value_score", "momentum_score"]
    ].mean(axis=1)
    return out


def quantile_forward_returns(panel: pd.DataFrame, factor_col: str, quantiles: int = 5) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for month, group in panel.dropna(subset=[factor_col, "forward_1m_return"]).groupby("month"):
        if group[factor_col].nunique() < 2:
            continue
        bucket_count = min(quantiles, group[factor_col].nunique())
        buckets = pd.qcut(group[factor_col], bucket_count, labels=False, duplicates="drop") + 1
        tmp = group.assign(bucket=buckets)
        rows.append(tmp[["month", "bucket", "forward_1m_return"]])
    if not rows:
        return pd.DataFrame()
    data = pd.concat(rows, ignore_index=True)
    summary = data.groupby("bucket").agg(
        observations=("forward_1m_return", "count"),
        avg_forward_1m_return=("forward_1m_return", "mean"),
        median_forward_1m_return=("forward_1m_return", "median"),
        win_rate=("forward_1m_return", lambda x: (x > 0).mean()),
    )
    return summary.round(4)


def factor_ic(panel: pd.DataFrame, factor_col: str) -> pd.DataFrame:
    rows = []
    for month, group in panel.dropna(subset=[factor_col, "forward_1m_return"]).groupby("month"):
        if len(group) < 5 or group[factor_col].nunique() < 2:
            continue
        rows.append(
            {
                "month": month,
                "rank_ic": group[factor_col].corr(group["forward_1m_return"], method="spearman"),
                "stocks": len(group),
            }
        )
    return pd.DataFrame(rows)


def summarize_ic(ic: pd.DataFrame) -> Dict[str, float]:
    if ic.empty:
        return {"months": 0, "avg_rank_ic": np.nan, "icir": np.nan, "positive_rate": np.nan}
    std = ic["rank_ic"].std(ddof=0)
    return {
        "months": int(len(ic)),
        "avg_rank_ic": round(float(ic["rank_ic"].mean()), 4),
        "icir": round(float(ic["rank_ic"].mean() / std), 4) if std and not np.isnan(std) else np.nan,
        "positive_rate": round(float((ic["rank_ic"] > 0).mean()), 4),
    }


def run_top_backtest(panel: pd.DataFrame, factor_col: str, top_n: int) -> pd.DataFrame:
    rows = []
    for month, group in panel.dropna(subset=[factor_col, "forward_1m_return"]).groupby("month"):
        ranked = group.sort_values(factor_col, ascending=False)
        selected = ranked.head(min(top_n, len(ranked)))
        rows.append(
            {
                "month": month,
                "strategy": factor_col,
                "selected": len(selected),
                "return": selected["forward_1m_return"].mean(),
                "benchmark_return": group["forward_1m_return"].mean(),
                "holdings": ",".join(selected["ts_code"].tolist()),
            }
        )
    return pd.DataFrame(rows)


def performance_metrics(returns: pd.Series) -> Dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {"months": 0}
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    years = len(returns) / 12
    total_return = equity.iloc[-1] - 1
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = returns.std(ddof=0) * np.sqrt(12)
    sharpe = (returns.mean() * 12) / vol if vol and not np.isnan(vol) else np.nan
    max_dd = drawdown.min()
    return {
        "months": int(len(returns)),
        "total_return": round(float(total_return), 4),
        "cagr": round(float(cagr), 4),
        "annual_vol": round(float(vol), 4),
        "max_drawdown": round(float(max_dd), 4),
        "sharpe_0rf": round(float(sharpe), 4) if not np.isnan(sharpe) else np.nan,
        "win_rate": round(float((returns > 0).mean()), 4),
    }


def run_research(config: ResearchConfig) -> Tuple[str, Dict[str, object]]:
    universe = discover_local_universe(config.cache_dir, config.kline_dir)
    full_universe_size = len(universe)
    if config.max_stocks is not None and config.max_stocks < len(universe):
        positions = np.linspace(0, len(universe) - 1, config.max_stocks, dtype=int)
        universe = [universe[pos] for pos in positions]
    panel = build_factor_panel(config, universe)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(config.output_dir, f"value_momentum_{timestamp}")
    os.makedirs(out_dir, exist_ok=True)

    stock_basic = load_stock_basic(config.cache_dir)
    if not stock_basic.empty and not panel.empty:
        cols = [c for c in ["ts_code", "name", "industry", "market"] if c in stock_basic.columns]
        panel = panel.merge(stock_basic[cols].drop_duplicates("ts_code"), on="ts_code", how="left")
    panel.to_csv(os.path.join(out_dir, "factor_panel.csv"), index=False, encoding="utf-8-sig")

    factor_cols = ["value_score", "momentum_score", "short_momentum_score", "composite_score"]
    quantile_tables = {}
    ic_summary = {}
    backtests = []
    for factor in factor_cols:
        q = quantile_forward_returns(panel, factor, config.quantiles)
        q.to_csv(os.path.join(out_dir, f"{factor}_quantiles.csv"), encoding="utf-8-sig")
        quantile_tables[factor] = q
        ic = factor_ic(panel, factor)
        ic.to_csv(os.path.join(out_dir, f"{factor}_ic.csv"), index=False, encoding="utf-8-sig")
        ic_summary[factor] = summarize_ic(ic)
        bt = run_top_backtest(panel, factor, config.top_n)
        bt.to_csv(os.path.join(out_dir, f"{factor}_top{config.top_n}_returns.csv"), index=False, encoding="utf-8-sig")
        backtests.append(bt)

    all_bt = pd.concat(backtests, ignore_index=True) if backtests else pd.DataFrame()
    all_bt.to_csv(os.path.join(out_dir, "top_backtests.csv"), index=False, encoding="utf-8-sig")
    perf_rows = []
    if not all_bt.empty:
        for strategy, group in all_bt.groupby("strategy"):
            row = {"strategy": strategy, **performance_metrics(group.sort_values("month")["return"])}
            perf_rows.append(row)
        bench = all_bt[all_bt["strategy"] == "value_score"].sort_values("month")
        perf_rows.append({"strategy": "equal_weight_universe", **performance_metrics(bench["benchmark_return"])})
    perf = pd.DataFrame(perf_rows)
    perf.to_csv(os.path.join(out_dir, "performance_summary.csv"), index=False, encoding="utf-8-sig")

    metadata = {
        "universe_size": len(universe),
        "full_universe_size": full_universe_size,
        "max_stocks": config.max_stocks,
        "kline_dir": config.kline_dir or os.path.join(config.cache_dir, "daily"),
        "panel_rows": len(panel),
        "months": int(panel["month"].nunique()) if not panel.empty else 0,
        "date_min": str(panel["month"].min().date()) if not panel.empty else "",
        "date_max": str(panel["month"].max().date()) if not panel.empty else "",
        "ic_summary": ic_summary,
    }
    pd.Series(metadata).to_csv(os.path.join(out_dir, "metadata.csv"), encoding="utf-8-sig")
    _write_markdown_report(out_dir, metadata, perf, quantile_tables)
    return out_dir, {"metadata": metadata, "performance": perf, "quantiles": quantile_tables}


def _write_markdown_report(
    out_dir: str,
    metadata: Dict[str, object],
    performance: pd.DataFrame,
    quantile_tables: Dict[str, pd.DataFrame],
) -> None:
    def table_text(df: pd.DataFrame) -> str:
        if df.empty:
            return "无数据。"
        return "```\n" + df.to_string() + "\n```"

    lines = [
        "# 价值 + 动量因子小样本验证报告",
        "",
        "## 样本说明",
        "",
        f"- 股票数量: {metadata['universe_size']}",
        f"- 因子面板记录: {metadata['panel_rows']}",
        f"- 月份数量: {metadata['months']}",
        f"- 日期范围: {metadata['date_min']} 至 {metadata['date_max']}",
        "",
        "当前报告基于本地 Tushare 缓存生成。若本地日线缓存股票数量或历史长度不足，结果只用于验证研究流程，不应作为最终策略结论。",
        "",
        "## 绩效摘要",
        "",
        table_text(performance.reset_index(drop=True)),
        "",
        "## 分组收益",
        "",
    ]
    for factor, table in quantile_tables.items():
        lines.extend(
            [
                f"### {factor}",
                "",
                table_text(table),
                "",
            ]
        )
    lines.extend(["## IC 摘要", ""])
    ic_summary = metadata.get("ic_summary", {})
    if isinstance(ic_summary, dict):
        lines.append(table_text(pd.DataFrame(ic_summary).T))
    else:
        lines.append(str(ic_summary))
    lines.append("")
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local value and momentum factors.")
    parser.add_argument("--cache-dir", default=os.path.expanduser("~/abu/tushare"))
    parser.add_argument("--kline-dir", default=None)
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--min-stocks-per-month", type=int, default=20)
    parser.add_argument("--min-price-months", type=int, default=14)
    parser.add_argument("--max-stocks", type=int, default=None)
    args = parser.parse_args()
    config = ResearchConfig(
        cache_dir=args.cache_dir,
        kline_dir=args.kline_dir,
        output_dir=args.output_dir,
        top_n=args.top_n,
        min_stocks_per_month=args.min_stocks_per_month,
        min_price_months=args.min_price_months,
        max_stocks=args.max_stocks,
    )
    out_dir, result = run_research(config)
    print(f"输出目录: {out_dir}")
    print("元数据:")
    for key, value in result["metadata"].items():
        print(f"  {key}: {value}")
    print("\n绩效摘要:")
    print(result["performance"].to_string(index=False))


if __name__ == "__main__":
    main()
