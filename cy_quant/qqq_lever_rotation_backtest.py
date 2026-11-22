#!/usr/bin/env python3
"""QQQ core + leveraged overlay rotation backtest on local csv_his data.

Strategies tested:
1) QQQ buy & hold
2) QQQ > MA120: keep 50% QQQ core and rotate the other 50% between
   QQQ and leveraged ETF (currently TQQQ due to local data availability)
3) QQQ Dual Thrust(N=120): same 50% overlay rotation logic

Execution uses close confirmation and close execution on daily bars.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PerfRow:
    strategy: str
    lever_symbol: str
    signal_type: str
    cost_bps: float
    start_date: str
    end_date: str
    trading_days: int
    switches: int
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    calmar: float
    final_value: float
    avg_lever_weight: float
    avg_qqq_weight: float
    signal_on_ratio: float


def _load_ohlc(path: str, symbol: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date_dt"] = pd.to_datetime(df["Unnamed: 0"], errors="coerce")
    cols = ["date_dt", "open", "close", "high", "low"]
    df = df.dropna(subset=["date_dt", "open", "close", "high", "low"]).sort_values("date_dt").reset_index(drop=True)
    df = df[cols].copy()
    return df.rename(
        columns={
            "open": f"{symbol}_open",
            "close": f"{symbol}_close",
            "high": f"{symbol}_high",
            "low": f"{symbol}_low",
        }
    )


def load_pair(qqq_path: str, lever_path: str, lever_symbol: str) -> pd.DataFrame:
    qqq = _load_ohlc(qqq_path, "qqq")
    lever = _load_ohlc(lever_path, lever_symbol)
    return qqq.merge(lever, on="date_dt", how="inner").sort_values("date_dt").reset_index(drop=True)


def add_ma120_signal(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["qqq_ma120"] = out["qqq_close"].rolling(120, min_periods=120).mean()
    out["signal_on"] = out["qqq_close"] > out["qqq_ma120"]
    return out.dropna(subset=["qqq_ma120"]).reset_index(drop=True)


def add_dual_thrust_signal(df: pd.DataFrame, n: int, k1: float, k2: float) -> pd.DataFrame:
    out = df.copy()
    hh = out["qqq_high"].shift(1).rolling(n, min_periods=n).max()
    lc = out["qqq_close"].shift(1).rolling(n, min_periods=n).min()
    hc = out["qqq_close"].shift(1).rolling(n, min_periods=n).max()
    ll = out["qqq_low"].shift(1).rolling(n, min_periods=n).min()
    rng = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)
    out["dt_range"] = rng
    out["dt_buy_line"] = out["qqq_open"] + k1 * rng
    out["dt_sell_line"] = out["qqq_open"] - k2 * rng

    signal_on = False
    states = []
    for _, r in out.iterrows():
        if pd.isna(r["dt_buy_line"]) or pd.isna(r["dt_sell_line"]):
            states.append(np.nan)
            continue
        if (not signal_on) and (r["qqq_high"] >= r["dt_buy_line"]):
            signal_on = True
        elif signal_on and (r["qqq_low"] <= r["dt_sell_line"]):
            signal_on = False
        states.append(signal_on)
    out["signal_on"] = states
    return out.dropna(subset=["signal_on"]).reset_index(drop=True)


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def _cagr(equity: pd.Series, dates: pd.Series, initial_capital: float = 1.0) -> float:
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0 or initial_capital <= 0:
        return np.nan
    return float((equity.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0)


def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().dropna()
    if ret.empty or ret.std(ddof=0) == 0:
        return np.nan
    return float(ret.mean() / ret.std(ddof=0) * np.sqrt(252))


def _perf_from_equity(
    equity: pd.DataFrame,
    strategy: str,
    lever_symbol: str,
    signal_type: str,
    cost_bps: float,
    switches: int,
) -> PerfRow:
    eq = equity["equity"].astype(float)
    cagr = _cagr(eq, equity["date"])
    max_dd = _max_drawdown(eq)
    return PerfRow(
        strategy=strategy,
        lever_symbol=lever_symbol,
        signal_type=signal_type,
        cost_bps=cost_bps,
        start_date=equity["date"].iloc[0].date().isoformat(),
        end_date=equity["date"].iloc[-1].date().isoformat(),
        trading_days=len(equity),
        switches=switches,
        total_return=float(eq.iloc[-1] - 1.0),
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=_sharpe(eq),
        calmar=float(cagr / abs(max_dd)) if max_dd < 0 and pd.notna(cagr) else np.nan,
        final_value=float(eq.iloc[-1]),
        avg_lever_weight=float(equity["lever_weight"].mean()),
        avg_qqq_weight=float(equity["qqq_weight"].mean()),
        signal_on_ratio=float(equity["signal_on"].mean()),
    )


def run_buy_hold(df: pd.DataFrame, cost_bps: float) -> tuple[PerfRow, pd.DataFrame]:
    cost = cost_bps / 10000.0
    qqq_shares = (1.0 - cost) / float(df["qqq_close"].iloc[0])
    out = df[["date_dt", "qqq_close"]].copy()
    out["qqq_value"] = qqq_shares * out["qqq_close"]
    out["lever_value"] = 0.0
    out["equity"] = out["qqq_value"]
    out["qqq_weight"] = 1.0
    out["lever_weight"] = 0.0
    out["signal_on"] = 0
    out["date"] = out["date_dt"]
    equity = out[["date", "equity", "qqq_weight", "lever_weight", "signal_on"]]
    return _perf_from_equity(equity, "qqq_buy_hold", "none", "none", cost_bps, 0), equity


def run_rotation(
    df: pd.DataFrame,
    lever_symbol: str,
    signal_type: str,
    cost_bps: float,
    strategy_name: str | None = None,
) -> tuple[PerfRow, pd.DataFrame, pd.DataFrame]:
    cost = cost_bps / 10000.0
    qqq_core_shares = (0.5 * (1.0 - cost)) / float(df["qqq_close"].iloc[0])
    overlay_qqq_shares = (0.5 * (1.0 - cost)) / float(df["qqq_close"].iloc[0])
    lever_shares = 0.0
    cash = 0.0
    switches = 0
    prev_signal = bool(df["signal_on"].iloc[0])
    trades = []
    equity_rows = []

    if prev_signal:
        qqq_px0 = float(df["qqq_close"].iloc[0])
        lever_px0 = float(df[f"{lever_symbol}_close"].iloc[0])
        proceeds = overlay_qqq_shares * qqq_px0 * (1.0 - cost)
        overlay_qqq_shares = 0.0
        lever_shares = proceeds * (1.0 - cost) / lever_px0
        switches += 1
        trades.append({"date": df["date_dt"].iloc[0], "type": "switch_on", "qqq_px": qqq_px0, "lever_px": lever_px0})

    for _, r in df.iterrows():
        date = r["date_dt"]
        qqq_px = float(r["qqq_close"])
        lever_px = float(r[f"{lever_symbol}_close"])
        signal_on = bool(r["signal_on"])
        action = "hold"

        if signal_on != prev_signal:
            switches += 1
            if signal_on:
                proceeds = overlay_qqq_shares * qqq_px * (1.0 - cost)
                overlay_qqq_shares = 0.0
                lever_shares += proceeds * (1.0 - cost) / lever_px
                action = "switch_on"
            else:
                proceeds = lever_shares * lever_px * (1.0 - cost)
                lever_shares = 0.0
                overlay_qqq_shares += proceeds * (1.0 - cost) / qqq_px
                action = "switch_off"
            trades.append({"date": date, "type": action, "qqq_px": qqq_px, "lever_px": lever_px})
            prev_signal = signal_on

        qqq_value = (qqq_core_shares + overlay_qqq_shares) * qqq_px
        lever_value = lever_shares * lever_px
        equity = qqq_value + lever_value + cash
        equity_rows.append(
            {
                "date": date,
                "equity": equity,
                "qqq_weight": qqq_value / equity if equity > 0 else np.nan,
                "lever_weight": lever_value / equity if equity > 0 else np.nan,
                "signal_on": int(signal_on),
                "action": action,
                "qqq_close": qqq_px,
                f"{lever_symbol}_close": lever_px,
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trades)
    perf = _perf_from_equity(
        equity,
        strategy_name or f"qqq50_{lever_symbol.lower()}50_rotation",
        lever_symbol,
        signal_type,
        cost_bps,
        switches,
    )
    return perf, equity, trades


def _write_report(out_dir: str, summary: pd.DataFrame, trades_by_name: dict[str, pd.DataFrame], args: argparse.Namespace) -> None:
    lines = [
        "# QQQ Lever Rotation Research",
        "",
        "## Config",
        "",
        f"- QQQ path: `{args.qqq_path}`",
        f"- Lever path: `{args.lever_path}`",
        f"- Lever symbol used: `{args.lever_symbol}`",
        f"- QLD availability: `missing in local csv_his, so this run uses TQQQ`",
        f"- Rotation rule: `50% core QQQ always held; the other 50% rotates between QQQ and leveraged ETF`",
        f"- MA filter: `QQQ close > MA120 => overlay goes to leveraged ETF`",
        f"- Dual Thrust window: `120`",
        f"- Cost bps: `{args.cost_bps}`",
        "",
        "## Summary",
        "",
        summary.to_markdown(index=False),
    ]
    for name, trades in trades_by_name.items():
        if not trades.empty:
            lines.extend(["", f"## {name} First 20 Switches", "", trades.head(20).to_markdown(index=False)])
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="QQQ leveraged overlay rotation backtest")
    parser.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    parser.add_argument("--lever-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    parser.add_argument("--lever-symbol", default="tqqq")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--dt-n", type=int, default=120)
    parser.add_argument("--dt-k-grid", default="0.3/0.3,0.5/0.5,0.7/0.7,0.5/0.3")
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    base = load_pair(args.qqq_path, args.lever_path, args.lever_symbol)
    ma_df = add_ma120_signal(base)
    dt_configs = []
    for part in args.dt_k_grid.split(","):
        left, right = part.split("/")
        k1 = float(left)
        k2 = float(right)
        dt_df = add_dual_thrust_signal(base, args.dt_n, k1, k2)
        dt_configs.append((k1, k2, dt_df))
    common_start = max([ma_df["date_dt"].iloc[0], *[cfg[2]["date_dt"].iloc[0] for cfg in dt_configs]])
    ma_df = ma_df[ma_df["date_dt"] >= common_start].reset_index(drop=True)
    dt_configs = [(k1, k2, dt_df[dt_df["date_dt"] >= common_start].reset_index(drop=True)) for k1, k2, dt_df in dt_configs]
    bh_df = base[base["date_dt"] >= common_start].reset_index(drop=True)

    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
    cost_tag = str(args.cost_bps).replace(".", "p")
    out_dir = os.path.join(args.output_dir, f"qqq_lever_rotation_{args.lever_symbol}_cost{cost_tag}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    bh_perf, bh_equity = run_buy_hold(bh_df, args.cost_bps)
    ma_perf, ma_equity, ma_trades = run_rotation(
        ma_df,
        args.lever_symbol,
        "ma120",
        args.cost_bps,
        strategy_name=f"qqq50_{args.lever_symbol.lower()}50_rotation_ma120",
    )

    perf_rows = [bh_perf.__dict__, ma_perf.__dict__]
    dt_trade_tables: dict[str, pd.DataFrame] = {}
    for k1, k2, dt_df in dt_configs:
        tag = f"dual_thrust_{args.dt_n}_k{k1:g}_{k2:g}"
        dt_perf, dt_equity, dt_trades = run_rotation(
            dt_df,
            args.lever_symbol,
            tag,
            args.cost_bps,
            strategy_name=f"qqq50_{args.lever_symbol.lower()}50_rotation_{tag}",
        )
        perf_rows.append(dt_perf.__dict__)
        dt_equity.to_csv(os.path.join(out_dir, f"equity_{tag}.csv"), index=False, encoding="utf-8-sig")
        dt_trades.to_csv(os.path.join(out_dir, f"trades_{tag}.csv"), index=False, encoding="utf-8-sig")
        dt_trade_tables[f"DualThrust {k1:g}/{k2:g}"] = dt_trades

    summary = pd.DataFrame(perf_rows).sort_values("strategy").reset_index(drop=True)
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    bh_equity.to_csv(os.path.join(out_dir, "equity_qqq_buy_hold.csv"), index=False, encoding="utf-8-sig")
    ma_equity.to_csv(os.path.join(out_dir, "equity_ma120_rotation.csv"), index=False, encoding="utf-8-sig")
    ma_trades.to_csv(os.path.join(out_dir, "trades_ma120_rotation.csv"), index=False, encoding="utf-8-sig")
    trade_tables = {"MA120": ma_trades}
    trade_tables.update(dt_trade_tables)
    _write_report(out_dir, summary, trade_tables, args)

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
