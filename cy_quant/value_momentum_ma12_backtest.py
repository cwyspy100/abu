"""First-pass A-share quality-value + momentum + 12M MA backtest.

The goal is validation, not a production trading engine. It uses the local
`astock` price files and Tushare finance files, applies finance data by
announcement date, and compares simple factor/risk-control variants.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


PRICE_RE = re.compile(r"^(sh|sz)(\d{6})_(\d{8})_(\d{8})$", re.IGNORECASE)


@dataclass(frozen=True)
class BacktestConfig:
    astock_dir: Path = Path("/Users/water/abu/data/csv/astock")
    finance_dir: Path = Path("/Users/water/abu/tushare/finance")
    output_dir: Path = Path("cy_quant/output")
    start: str = "2014-07-31"
    end: str = "2025-06-30"
    benchmark_code: str = "000300.SH"
    top_ns: Tuple[int, ...] = (10, 15, 20)
    min_price_months: int = 18
    min_avg_volume: float = 100_000.0
    min_candidates_per_month: int = 100
    cost_per_turnover: float = 0.003
    max_stocks: Optional[int] = None
    panel_csv: Optional[Path] = None


def _parse_yyyymmdd(value) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    return pd.to_datetime(str(value).split(".")[0], format="%Y%m%d", errors="coerce")


def ts_code_from_price_path(path: Path) -> Optional[str]:
    match = PRICE_RE.match(path.name)
    if not match:
        return None
    market, code, _, _ = match.groups()
    return f"{code}.{market.upper()}"


def price_prefix_for_ts_code(ts_code: str) -> str:
    code, market = ts_code.split(".")
    return f"{market.lower()}{code}"


def latest_price_files(astock_dir: Path) -> Dict[str, Path]:
    rows = []
    for path in astock_dir.iterdir():
        if not path.is_file():
            continue
        ts_code = ts_code_from_price_path(path)
        if ts_code is None:
            continue
        end_text = path.name.rsplit("_", 1)[-1]
        rows.append({"ts_code": ts_code, "path": path, "end": _parse_yyyymmdd(end_text)})
    if not rows:
        return {}
    df = pd.DataFrame(rows).sort_values(["ts_code", "end"])
    return dict(zip(df.groupby("ts_code", as_index=False).tail(1)["ts_code"], df.groupby("ts_code", as_index=False).tail(1)["path"]))


def load_stock_basic(finance_dir: Path) -> pd.DataFrame:
    path = finance_dir / "stock_basic_all.csv"
    if not path.exists():
        return pd.DataFrame(columns=["ts_code", "name", "industry", "market"])
    df = pd.read_csv(path)
    cols = [col for col in ["ts_code", "symbol", "name", "industry", "area", "market"] if col in df.columns]
    return df[cols].drop_duplicates("ts_code")


def finance_path(finance_dir: Path, ts_code: str) -> Path:
    code, market = ts_code.split(".")
    return finance_dir / f"{code}_{market}_finance.csv"


def discover_universe(config: BacktestConfig) -> List[str]:
    price_files = latest_price_files(config.astock_dir)
    stock_basic = load_stock_basic(config.finance_dir)
    if stock_basic.empty:
        basic_codes: set[str] = set()
        st_codes: set[str] = set()
    else:
        basic_codes = set(stock_basic["ts_code"].astype(str))
        st_codes = set(
            stock_basic[
                stock_basic.get("name", pd.Series(index=stock_basic.index, dtype=str))
                .astype(str)
                .str.contains("ST", case=False, na=False)
            ]["ts_code"].astype(str)
        )
    universe = []
    for ts_code in sorted(price_files):
        if ts_code not in basic_codes:
            continue
        if ts_code in st_codes:
            continue
        if finance_path(config.finance_dir, ts_code).exists():
            universe.append(ts_code)
    if config.max_stocks is not None and config.max_stocks < len(universe):
        positions = np.linspace(0, len(universe) - 1, config.max_stocks, dtype=int)
        universe = [universe[pos] for pos in positions]
    return universe


def load_daily_price(path: Path) -> pd.DataFrame:
    needed = {"date", "open", "close", "high", "low", "volume", "pre_close", "p_change"}
    df = pd.read_csv(path, usecols=lambda col: col in needed)
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    df["trade_date"] = df["date"].apply(_parse_yyyymmdd)
    for col in ["open", "close", "high", "low", "volume", "pre_close", "p_change"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["trade_date", "close"]).sort_values("trade_date")


def monthly_price_for_code(path: Path, ts_code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    daily = load_daily_price(path)
    if daily.empty:
        return pd.DataFrame()
    daily = daily[(daily["trade_date"] >= start - pd.DateOffset(months=14)) & (daily["trade_date"] <= end)]
    if daily.empty:
        return pd.DataFrame()
    daily["month"] = daily["trade_date"].dt.to_period("M").dt.to_timestamp("M")
    last = daily.groupby("month", as_index=False).tail(1)[["month", "trade_date", "close"]]
    avg_volume = daily.groupby("month", as_index=False)["volume"].mean().rename(columns={"volume": "avg_volume"})
    out = last.merge(avg_volume, on="month", how="left")
    out["ts_code"] = ts_code
    return out[["month", "ts_code", "trade_date", "close", "avg_volume"]]


def build_monthly_price_panel(config: BacktestConfig, universe: Iterable[str]) -> pd.DataFrame:
    files = latest_price_files(config.astock_dir)
    start = pd.Timestamp(config.start)
    end = pd.Timestamp(config.end)
    frames = []
    for ts_code in universe:
        path = files.get(ts_code)
        if path is None:
            continue
        frame = monthly_price_for_code(path, ts_code, start, end)
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_finance_asof(finance_dir: Path, ts_code: str) -> pd.DataFrame:
    path = finance_path(finance_dir, ts_code)
    if not path.exists():
        return pd.DataFrame()
    needed = {
        "ts_code",
        "ann_date_x",
        "ann_date_y",
        "f_ann_date",
        "ann_date",
        "end_date",
        "roe",
        "gross_margin",
        "netprofit_margin",
        "grossprofit_margin",
        "debt_to_assets",
        "current_ratio",
        "quick_ratio",
        "ocfps",
        "tr_yoy",
        "or_yoy",
        "netprofit_yoy",
        "dt_netprofit_yoy",
        "roe_yoy",
        "q_roe",
    }
    df = pd.read_csv(path, usecols=lambda col: col in needed)
    ann = pd.Series(pd.NaT, index=df.index)
    for col in ["ann_date_x", "ann_date_y", "f_ann_date", "ann_date"]:
        if col in df.columns:
            ann = ann.fillna(df[col].apply(_parse_yyyymmdd))
    out = pd.DataFrame({"ann_date": ann})
    out["finance_end_date"] = df["end_date"].apply(_parse_yyyymmdd) if "end_date" in df.columns else pd.NaT
    factor_cols = sorted((needed - {"ts_code", "ann_date_x", "ann_date_y", "f_ann_date", "ann_date", "end_date"}))
    for col in factor_cols:
        out[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else np.nan
    out = out.dropna(subset=["ann_date"]).sort_values("ann_date")
    return out


def add_finance_asof(panel: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    frames = []
    for ts_code, prices in panel.groupby("ts_code"):
        finance = load_finance_asof(config.finance_dir, ts_code)
        if finance.empty:
            continue
        left = prices.sort_values("month")
        merged = pd.merge_asof(
            left,
            finance,
            left_on="month",
            right_on="ann_date",
            direction="backward",
        )
        frames.append(merged)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def add_price_factors(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.sort_values(["ts_code", "month"]).copy()
    grouped = out.groupby("ts_code")
    out["ret_1m"] = grouped["close"].pct_change()
    out["forward_1m_return"] = grouped["close"].shift(-1) / out["close"] - 1
    out["momentum_3m"] = grouped["close"].transform(lambda x: x / x.shift(3) - 1)
    out["momentum_6m"] = grouped["close"].transform(lambda x: x / x.shift(6) - 1)
    out["momentum_12_1"] = grouped["close"].transform(lambda x: x.shift(1) / x.shift(12) - 1)
    out["ma12"] = grouped["close"].transform(lambda x: x.rolling(12, min_periods=12).mean())
    out["ma12_distance"] = out["close"] / out["ma12"] - 1
    vol6 = grouped["ret_1m"].transform(lambda x: x.rolling(6, min_periods=4).std(ddof=0))
    out["risk_adjusted_momentum"] = out["momentum_6m"] / vol6.replace(0, np.nan)
    return out


def _rank_pct(grouped, col: str, ascending: bool = True) -> pd.Series:
    return grouped[col].rank(pct=True, ascending=ascending)


def add_scores(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    grouped = out.groupby("month", group_keys=False)
    out["quality_score"] = pd.concat(
        [
            _rank_pct(grouped, "roe"),
            _rank_pct(grouped, "grossprofit_margin"),
            _rank_pct(grouped, "netprofit_margin"),
        ],
        axis=1,
    ).mean(axis=1)
    out["stability_score"] = pd.concat(
        [
            _rank_pct(grouped, "debt_to_assets", ascending=False),
            _rank_pct(grouped, "current_ratio"),
            _rank_pct(grouped, "quick_ratio"),
            _rank_pct(grouped, "ocfps"),
        ],
        axis=1,
    ).mean(axis=1)
    out["improvement_score"] = pd.concat(
        [
            _rank_pct(grouped, "tr_yoy"),
            _rank_pct(grouped, "or_yoy"),
            _rank_pct(grouped, "netprofit_yoy"),
            _rank_pct(grouped, "dt_netprofit_yoy"),
            _rank_pct(grouped, "roe_yoy"),
            _rank_pct(grouped, "q_roe"),
        ],
        axis=1,
    ).mean(axis=1)
    out["finance_quality_score"] = out[["quality_score", "stability_score", "improvement_score"]].mean(axis=1)
    out["momentum_score"] = pd.concat(
        [
            _rank_pct(grouped, "momentum_3m"),
            _rank_pct(grouped, "momentum_6m"),
            _rank_pct(grouped, "momentum_12_1"),
            _rank_pct(grouped, "ma12_distance"),
            _rank_pct(grouped, "risk_adjusted_momentum"),
        ],
        axis=1,
    ).mean(axis=1)
    out["momentum_6_12_score"] = pd.concat(
        [
            _rank_pct(grouped, "momentum_6m"),
            _rank_pct(grouped, "momentum_12_1"),
            _rank_pct(grouped, "risk_adjusted_momentum"),
        ],
        axis=1,
    ).mean(axis=1)
    out["trend_score"] = pd.concat(
        [
            _rank_pct(grouped, "ma12_distance"),
            _rank_pct(grouped, "momentum_12_1"),
            _rank_pct(grouped, "risk_adjusted_momentum"),
        ],
        axis=1,
    ).mean(axis=1)
    for value_col in ["quality_score", "stability_score", "improvement_score", "finance_quality_score"]:
        out[f"{value_col}_vm50"] = out[[value_col, "momentum_score"]].mean(axis=1)
        out[f"{value_col}_vm30"] = out[value_col] * 0.3 + out["momentum_score"] * 0.7
        out[f"{value_col}_vm70"] = out[value_col] * 0.7 + out["momentum_score"] * 0.3
        out[f"{value_col}_vm80"] = out[value_col] * 0.8 + out["momentum_score"] * 0.2
        out[f"{value_col}_vm90"] = out[value_col] * 0.9 + out["momentum_score"] * 0.1
    return out


def load_benchmark_monthly(config: BacktestConfig) -> pd.DataFrame:
    files = latest_price_files(config.astock_dir)
    path = files.get(config.benchmark_code)
    if path is None:
        prefix = price_prefix_for_ts_code(config.benchmark_code)
        matches = sorted(config.astock_dir.glob(f"{prefix}_*"))
        path = matches[-1] if matches else None
    if path is None:
        return pd.DataFrame()
    monthly = monthly_price_for_code(path, config.benchmark_code, pd.Timestamp(config.start), pd.Timestamp(config.end))
    monthly = monthly.sort_values("month")
    monthly["benchmark_return"] = monthly["close"].pct_change()
    monthly["benchmark_ma12"] = monthly["close"].rolling(12, min_periods=12).mean()
    monthly["benchmark_ma12_distance"] = monthly["close"] / monthly["benchmark_ma12"] - 1
    return monthly[["month", "benchmark_return", "benchmark_ma12_distance"]]


def exposure_from_distance(distance: float) -> float:
    if pd.isna(distance) or distance >= 0:
        return 1.0
    if distance >= -0.05:
        return 0.7
    if distance >= -0.10:
        return 0.5
    return 0.3


def exposure_from_risk_mode(distance: float, risk_mode: str) -> float:
    if risk_mode in {"market_ma_strict", "dual_ma_strict"}:
        return 1.0 if pd.notna(distance) and distance >= 0 else 0.0
    if risk_mode in {"market_ma_floor0", "dual_ma_floor0"}:
        if pd.isna(distance) or distance >= 0:
            return 1.0
        if distance >= -0.05:
            return 0.5
        if distance >= -0.10:
            return 0.2
        return 0.0
    return exposure_from_distance(distance)


def run_monthly_top_backtest(
    panel: pd.DataFrame,
    benchmark: pd.DataFrame,
    score_col: str,
    top_n: int,
    risk_mode: str,
    config: BacktestConfig,
) -> pd.DataFrame:
    bench = benchmark.set_index("month")
    rows = []
    prev_weights: Dict[str, float] = {}
    for month, group in panel.groupby("month"):
        if month not in bench.index:
            continue
        group = group.dropna(subset=[score_col, "forward_1m_return", "avg_volume"])
        group = group[group["avg_volume"] >= config.min_avg_volume]
        if len(group) < max(config.min_candidates_per_month, top_n):
            continue
        if risk_mode in {"stock_ma", "dual_ma", "dual_ma_strict", "dual_ma_floor0"}:
            group = group[group["ma12_distance"] > 0]
        group = group.sort_values(score_col, ascending=False).head(top_n)
        market_exposure = exposure_from_risk_mode(float(bench.at[month, "benchmark_ma12_distance"]), risk_mode)
        exposure = (
            market_exposure
            if risk_mode in {"market_ma", "dual_ma", "market_ma_strict", "dual_ma_strict", "market_ma_floor0", "dual_ma_floor0"}
            else 1.0
        )
        if group.empty:
            weights: Dict[str, float] = {}
            gross_return = 0.0
        else:
            weight = exposure / len(group)
            weights = dict(zip(group["ts_code"], [weight] * len(group)))
            gross_return = float((group["forward_1m_return"] * weight).sum())
        traded = sum(abs(weights.get(code, 0.0) - prev_weights.get(code, 0.0)) for code in set(weights) | set(prev_weights))
        cost = traded * config.cost_per_turnover
        net_return = gross_return - cost
        rows.append(
            {
                "month": month,
                "strategy": f"{score_col}|top{top_n}|{risk_mode}",
                "score_col": score_col,
                "top_n": top_n,
                "risk_mode": risk_mode,
                "selected": len(group),
                "exposure": exposure,
                "turnover_notional": traded,
                "cost": cost,
                "gross_return": gross_return,
                "return": net_return,
                "benchmark_return": float(bench.at[month, "benchmark_return"]),
                "holdings": ",".join(group["ts_code"].tolist()),
            }
        )
        prev_weights = weights
    return pd.DataFrame(rows)


def performance_metrics(returns: pd.Series, benchmark_returns: Optional[pd.Series] = None) -> Dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {"months": 0}
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    years = len(returns) / 12
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = returns.std(ddof=0) * np.sqrt(12)
    downside = returns[returns < 0].std(ddof=0) * np.sqrt(12)
    sharpe = returns.mean() * 12 / vol if vol and not np.isnan(vol) else np.nan
    sortino = returns.mean() * 12 / downside if downside and not np.isnan(downside) else np.nan
    row = {
        "months": int(len(returns)),
        "total_return": round(float(equity.iloc[-1] - 1), 4),
        "cagr": round(float(cagr), 4),
        "annual_vol": round(float(vol), 4),
        "max_drawdown": round(float(drawdown.min()), 4),
        "sharpe_0rf": round(float(sharpe), 4) if not np.isnan(sharpe) else np.nan,
        "sortino_0rf": round(float(sortino), 4) if not np.isnan(sortino) else np.nan,
        "win_rate": round(float((returns > 0).mean()), 4),
        "positive_years": int((returns.groupby(returns.index.year).apply(lambda x: (1 + x).prod() - 1) > 0).sum()),
        "years": int(returns.index.year.nunique()),
    }
    if benchmark_returns is not None:
        aligned = pd.concat([returns.rename("r"), benchmark_returns.rename("b")], axis=1).dropna()
        if not aligned.empty:
            excess = aligned["r"] - aligned["b"]
            row["avg_annual_excess"] = round(float(excess.mean() * 12), 4)
            row["excess_positive_rate"] = round(float((excess > 0).mean()), 4)
            rolling_36 = (1 + aligned["r"]).rolling(36).apply(np.prod, raw=True) - 1
            row["rolling_36m_min"] = round(float(rolling_36.min()), 4) if rolling_36.notna().any() else np.nan
    return row


def build_factor_panel(config: BacktestConfig, universe: List[str]) -> pd.DataFrame:
    prices = build_monthly_price_panel(config, universe)
    if prices.empty:
        return pd.DataFrame()
    counts = prices.groupby("ts_code")["month"].nunique()
    valid_codes = set(counts[counts >= config.min_price_months].index)
    prices = prices[prices["ts_code"].isin(valid_codes)]
    prices = add_price_factors(prices)
    panel = add_finance_asof(prices, config)
    if panel.empty:
        return pd.DataFrame()
    panel = panel[(panel["month"] >= pd.Timestamp(config.start)) & (panel["month"] <= pd.Timestamp(config.end))]
    return add_scores(panel)


def run_validation(config: BacktestConfig) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.output_dir / f"value_momentum_ma12_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = discover_universe(config)
    benchmark = load_benchmark_monthly(config)
    if config.panel_csv is not None:
        panel = pd.read_csv(config.panel_csv, parse_dates=["month", "trade_date", "ann_date", "finance_end_date"])
        panel = add_scores(panel)
    else:
        panel = build_factor_panel(config, universe)
    stock_basic = load_stock_basic(config.finance_dir)
    if not stock_basic.empty and not panel.empty:
        cols = [col for col in ["ts_code", "name", "industry", "market"] if col in stock_basic.columns]
        panel = panel.merge(stock_basic[cols], on="ts_code", how="left")
    panel.to_csv(out_dir / "factor_panel.csv", index=False, encoding="utf-8-sig")
    benchmark.to_csv(out_dir / "benchmark_monthly.csv", index=False, encoding="utf-8-sig")

    score_cols = [
        "finance_quality_score",
        "quality_score_vm50",
        "stability_score_vm50",
        "improvement_score_vm50",
        "finance_quality_score_vm50",
        "finance_quality_score_vm30",
        "finance_quality_score_vm70",
        "finance_quality_score_vm80",
        "finance_quality_score_vm90",
        "momentum_score",
        "momentum_6_12_score",
        "trend_score",
    ]
    score_cols = [col for col in score_cols if col in panel.columns]
    risk_modes = [
        "none",
        "market_ma",
        "market_ma_floor0",
        "market_ma_strict",
        "stock_ma",
        "dual_ma",
        "dual_ma_floor0",
        "dual_ma_strict",
    ]
    backtests = []
    for score_col in score_cols:
        for top_n in config.top_ns:
            for risk_mode in risk_modes:
                bt = run_monthly_top_backtest(panel, benchmark, score_col, top_n, risk_mode, config)
                if not bt.empty:
                    backtests.append(bt)
    all_bt = pd.concat(backtests, ignore_index=True) if backtests else pd.DataFrame()
    all_bt.to_csv(out_dir / "monthly_backtests.csv", index=False, encoding="utf-8-sig")

    perf_rows = []
    if not all_bt.empty:
        for strategy, group in all_bt.groupby("strategy"):
            monthly = group.sort_values("month").set_index("month")
            row = {"strategy": strategy, **performance_metrics(monthly["return"], monthly["benchmark_return"])}
            row["avg_exposure"] = round(float(monthly["exposure"].mean()), 4)
            row["avg_selected"] = round(float(monthly["selected"].mean()), 2)
            row["avg_turnover_notional"] = round(float(monthly["turnover_notional"].mean()), 4)
            perf_rows.append(row)
    perf = pd.DataFrame(perf_rows).sort_values(["cagr", "max_drawdown"], ascending=[False, False])
    perf.to_csv(out_dir / "performance_summary.csv", index=False, encoding="utf-8-sig")

    bench_returns = benchmark.dropna(subset=["benchmark_return"]).set_index("month")["benchmark_return"]
    pd.DataFrame([{"strategy": "hs300", **performance_metrics(bench_returns)}]).to_csv(
        out_dir / "benchmark_performance.csv", index=False, encoding="utf-8-sig"
    )
    write_report(out_dir, config, universe, panel, perf)
    return out_dir


def write_report(out_dir: Path, config: BacktestConfig, universe: List[str], panel: pd.DataFrame, perf: pd.DataFrame) -> None:
    top = perf.head(20) if not perf.empty else pd.DataFrame()
    candidates = perf[(perf["cagr"] >= 0.15) & (perf["max_drawdown"] >= -0.20)] if not perf.empty else pd.DataFrame()
    lines = [
        "# Value Momentum MA12 Validation",
        "",
        "## Scope",
        "",
        f"- price source: {config.astock_dir}",
        f"- finance source: {config.finance_dir}",
        f"- date range: {config.start} to {config.end}",
        f"- discovered universe: {len(universe)}",
        f"- factor panel rows: {len(panel)}",
        f"- months: {panel['month'].nunique() if not panel.empty else 0}",
        f"- conservative cost per notional traded: {config.cost_per_turnover}",
        f"- min average monthly-day volume: {config.min_avg_volume}",
        f"- min candidates per month: {config.min_candidates_per_month}",
        "",
        "## SPEC Gate",
        "",
        f"- strategies meeting CAGR >= 15% and max drawdown <= 20%: {len(candidates)}",
        "",
        "## Top 20 By CAGR",
        "",
    ]
    if top.empty:
        lines.append("No performance data.")
    else:
        cols = [
            "strategy",
            "months",
            "cagr",
            "max_drawdown",
            "sharpe_0rf",
            "sortino_0rf",
            "avg_annual_excess",
            "rolling_36m_min",
            "avg_exposure",
            "avg_selected",
            "avg_turnover_notional",
        ]
        lines.append("```")
        lines.append(top[[col for col in cols if col in top.columns]].to_string(index=False))
        lines.append("```")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This first pass uses current `stock_basic_all.csv` names for ST filtering, not historical ST status.",
            "- Turnover amount is unavailable, so liquidity is proxied by share volume.",
            "- Limit-up/down and suspension execution constraints are not yet modeled.",
            "- The result is research evidence only; it is not a live trading signal.",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> BacktestConfig:
    parser = argparse.ArgumentParser(description="Run first-pass value momentum MA12 validation.")
    parser.add_argument("--astock-dir", default="/Users/water/abu/data/csv/astock")
    parser.add_argument("--finance-dir", default="/Users/water/abu/tushare/finance")
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--start", default="2014-07-31")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument("--top-ns", default="10,15,20")
    parser.add_argument("--min-avg-volume", type=float, default=100_000.0)
    parser.add_argument("--min-candidates-per-month", type=int, default=100)
    parser.add_argument("--cost-per-turnover", type=float, default=0.003)
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--panel-csv", default=None)
    args = parser.parse_args()
    return BacktestConfig(
        astock_dir=Path(args.astock_dir),
        finance_dir=Path(args.finance_dir),
        output_dir=Path(args.output_dir),
        start=args.start,
        end=args.end,
        top_ns=tuple(int(x) for x in args.top_ns.split(",") if x.strip()),
        min_avg_volume=args.min_avg_volume,
        min_candidates_per_month=args.min_candidates_per_month,
        cost_per_turnover=args.cost_per_turnover,
        max_stocks=args.max_stocks,
        panel_csv=Path(args.panel_csv) if args.panel_csv else None,
    )


def main() -> None:
    out_dir = run_validation(parse_args())
    print(f"输出目录: {out_dir}")
    print(f"报告: {out_dir / 'README.md'}")


if __name__ == "__main__":
    main()
